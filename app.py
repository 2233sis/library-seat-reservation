from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from datetime import datetime, timedelta, date
import os

app = Flask(__name__)
CORS(app)

# Database setup
engine = create_engine('sqlite:///library_seats.db', echo=False)
db_session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Secret key for tokens
SECRET_KEY = 'library-seat-reservation-secret-key-2024'
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Models
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, index=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(20), default='user')
    violation_count = Column(Integer, default=0)
    is_blacklisted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Seat(Base):
    __tablename__ = 'seats'
    id = Column(Integer, primary_key=True)
    seat_number = Column(String(20), unique=True, index=True, nullable=False)
    type = Column(String(20), nullable=False)  # single/meeting
    capacity = Column(Integer, default=1)
    has_power = Column(Boolean, default=False)
    location = Column(String(100))
    is_active = Column(Boolean, default=True)

class Booking(Base):
    __tablename__ = 'bookings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    seat_id = Column(Integer, ForeignKey('seats.id'), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    start_time = Column(String(5), nullable=False)  # HH:MM
    end_time = Column(String(5), nullable=False)  # HH:MM
    status = Column(String(20), default='booked')  # booked/used/cancelled/violated
    companion_ids = Column(String(200), nullable=True)
    check_in_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', backref='bookings')
    seat = relationship('Seat', backref='bookings')

# Create tables
Base.metadata.create_all(bind=engine)

# Helper functions
def generate_token(user):
    payload = {'user_id': user.id, 'username': user.username, 'role': user.role}
    return serializer.dumps(payload)

def verify_token(token):
    try:
        data = serializer.loads(token, max_age=7776000)  # 90 days (covers marking window)
        return data
    except (SignatureExpired, BadSignature):
        return None

def token_required(f):
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'error': 'Authentication required', 'code': 'AUTH_001'}), 401
        data = verify_token(token)
        if not data:
            return jsonify({'error': 'Invalid or expired token', 'code': 'AUTH_001'}), 401
        user = db_session.query(User).get(data['user_id'])
        if not user:
            return jsonify({'error': 'User not found', 'code': 'AUTH_001'}), 401
        if user.is_blacklisted:
            return jsonify({'error': 'User is blacklisted', 'code': 'PERM_001'}), 403
        return f(user, *args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

def admin_required(f):
    def decorated(user, *args, **kwargs):
        if user.role != 'admin':
            return jsonify({'error': 'Admin access required', 'code': 'PERM_001'}), 403
        return f(user, *args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

def check_conflict(seat_id, date_str, start_time, end_time, exclude_booking_id=None):
    query = db_session.query(Booking).filter(
        Booking.seat_id == seat_id,
        Booking.date == date_str,
        Booking.status.in_(['booked', 'used']),
        Booking.start_time < end_time,
        Booking.end_time > start_time
    )
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    return query.first() is not None

def has_active_booking(user_id, exclude_booking_id=None):
    query = db_session.query(Booking).filter(
        Booking.user_id == user_id,
        Booking.status.in_(['booked', 'used'])
    )
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    return query.first() is not None

def validate_time_range(start_time, end_time):
    try:
        start = datetime.strptime(start_time, '%H:%M')
        end = datetime.strptime(end_time, '%H:%M')
        if end <= start:
            return False, 'End time must be after start time'
        duration = (end - start).seconds / 60
        if duration > 60:
            return False, 'Maximum booking duration is 1 hour'
        if start.hour < 8 or end.hour > 22 or (end.hour == 22 and end.minute > 0):
            return False, 'Booking must be between 08:00 and 22:00'
        return True, None
    except ValueError:
        return False, 'Invalid time format'

def process_violations():
    session = sessionmaker(bind=engine)()
    try:
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        current_time = now.strftime('%H:%M')
        
        # Find bookings that are late (no check-in 15 minutes after start)
        late_bookings = session.query(Booking).filter(
            Booking.date == today,
            Booking.status == 'booked',
            Booking.start_time < current_time,
            Booking.check_in_time == None
        ).all()
        
        for booking in late_bookings:
            start = datetime.strptime(booking.start_time, '%H:%M')
            current = datetime.strptime(current_time, '%H:%M')
            if (current - start).seconds / 60 > 15:
                booking.status = 'violated'
                user = session.query(User).get(booking.user_id)
                if user:
                    user.violation_count += 1
                    if user.violation_count >= 3:
                        user.is_blacklisted = True
        
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204

# Public routes
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Missing required fields', 'code': 'PARAM_001', 'details': ['username and password required']}), 400
    
    username = data['username'].strip()
    password = data['password']
    
    if len(username) < 3 or len(password) < 6:
        return jsonify({'error': 'Invalid input', 'code': 'PARAM_001', 'details': ['Username min 3 chars, password min 6 chars']}), 400
    
    existing = db_session.query(User).filter_by(username=username).first()
    if existing:
        return jsonify({'error': 'Username already exists', 'code': 'BUS_001'}), 409
    
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role='user'
    )
    db_session.add(user)
    db_session.commit()
    
    token = generate_token(user)
    return jsonify({
        'token': token,
        'user': {'id': user.id, 'username': user.username, 'role': user.role}
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Missing credentials', 'code': 'PARAM_001', 'details': ['username and password required']}), 400
    
    user = db_session.query(User).filter_by(username=data['username'].strip()).first()
    if not user or not check_password_hash(user.password_hash, data['password']):
        return jsonify({'error': 'Invalid credentials', 'code': 'AUTH_001'}), 401
    
    if user.is_blacklisted:
        return jsonify({'error': 'User is blacklisted', 'code': 'PERM_001'}), 403
    
    token = generate_token(user)
    return jsonify({
        'token': token,
        'user': {'id': user.id, 'username': user.username, 'role': user.role}
    })

@app.route('/api/seats', methods=['GET'])
def get_seats():
    process_violations()
    today = date.today().strftime('%Y-%m-%d')
    now_time = datetime.now().strftime('%H:%M')
    
    seats = db_session.query(Seat).filter_by(is_active=True).all()
    seat_list = []
    
    for seat in seats:
        # Check if there's an active booking for this seat now
        active_booking = db_session.query(Booking).filter(
            Booking.seat_id == seat.id,
            Booking.date == today,
            Booking.status.in_(['booked', 'used']),
            Booking.start_time <= now_time,
            Booking.end_time > now_time
        ).first()
        
        seat_data = {
            'id': seat.id,
            'seat_number': seat.seat_number,
            'type': seat.type,
            'capacity': seat.capacity,
            'has_power': seat.has_power,
            'location': seat.location,
            'status': 'occupied' if active_booking else 'free'
        }
        seat_list.append(seat_data)
    
    return jsonify({'seats': seat_list, 'date': today})

@app.route('/api/seats/<int:seat_id>/schedule', methods=['GET'])
def get_seat_schedule(seat_id):
    process_violations()
    seat = db_session.query(Seat).get(seat_id)
    if not seat:
        return jsonify({'error': 'Seat not found', 'code': 'RES_001'}), 404
    
    today = date.today().strftime('%Y-%m-%d')
    bookings = db_session.query(Booking).filter(
        Booking.seat_id == seat_id,
        Booking.date == today,
        Booking.status.in_(['booked', 'used', 'violated'])
    ).order_by(Booking.start_time).all()
    
    schedule = []
    for booking in bookings:
        schedule.append({
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'status': booking.status,
            'user_id': booking.user_id
        })
    
    return jsonify({'seat_id': seat_id, 'date': today, 'schedule': schedule})

# Authenticated user routes
@app.route('/api/bookings', methods=['POST'])
@token_required
def create_booking(user):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing data', 'code': 'PARAM_001', 'details': ['Request body required']}), 400
    
    seat_id = data.get('seat_id')
    date_str = data.get('date')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    companion_ids = data.get('companion_ids', '')
    
    if not all([seat_id, date_str, start_time, end_time]):
        return jsonify({'error': 'Missing required fields', 'code': 'PARAM_001', 'details': ['seat_id, date, start_time, end_time required']}), 400
    
    # Validate date
    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        if booking_date < date.today():
            return jsonify({'error': 'Cannot book in the past', 'code': 'PARAM_001', 'details': ['Date must be today or future']}), 400
    except ValueError:
        return jsonify({'error': 'Invalid date format', 'code': 'PARAM_001', 'details': ['Use YYYY-MM-DD']}), 400
    
    # Validate time range
    valid, error_msg = validate_time_range(start_time, end_time)
    if not valid:
        return jsonify({'error': error_msg, 'code': 'PARAM_001', 'details': [error_msg]}), 400
    
    # Check seat exists and is active
    seat = db_session.query(Seat).get(seat_id)
    if not seat or not seat.is_active:
        return jsonify({'error': 'Seat not found or inactive', 'code': 'RES_001'}), 404
    
    # Check companion IDs for meeting rooms
    if seat.type == 'meeting' and not companion_ids:
        return jsonify({'error': 'Meeting rooms require companion student IDs', 'code': 'PARAM_001', 'details': ['companion_ids required for meeting rooms']}), 400
    
    # Check if user has active booking
    if has_active_booking(user.id):
        return jsonify({'error': 'You already have an active booking', 'code': 'BUS_001'}), 409
    
    # Check for conflicts
    if check_conflict(seat_id, date_str, start_time, end_time):
        return jsonify({'error': 'Time slot already booked', 'code': 'BUS_001'}), 409
    
    booking = Booking(
        user_id=user.id,
        seat_id=seat_id,
        date=date_str,
        start_time=start_time,
        end_time=end_time,
        status='booked',
        companion_ids=companion_ids if companion_ids else None
    )
    db_session.add(booking)
    db_session.commit()
    
    return jsonify({
        'booking': {
            'id': booking.id,
            'seat_id': booking.seat_id,
            'date': booking.date,
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'status': booking.status,
            'companion_ids': booking.companion_ids
        }
    }), 201

@app.route('/api/my-bookings', methods=['GET'])
@token_required
def get_my_bookings(user):
    process_violations()
    bookings = db_session.query(Booking).filter_by(user_id=user.id).order_by(Booking.date.desc(), Booking.start_time).all()
    
    booking_list = []
    for booking in bookings:
        seat = db_session.query(Seat).get(booking.seat_id)
        booking_list.append({
            'id': booking.id,
            'seat_id': booking.seat_id,
            'seat_number': seat.seat_number if seat else 'Unknown',
            'date': booking.date,
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'status': booking.status,
            'companion_ids': booking.companion_ids,
            'check_in_time': booking.check_in_time.isoformat() if booking.check_in_time else None
        })
    
    return jsonify({'bookings': booking_list})

@app.route('/api/bookings/<int:booking_id>', methods=['DELETE'])
@token_required
def cancel_booking(user, booking_id):
    booking = db_session.query(Booking).get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found', 'code': 'RES_001'}), 404
    
    if booking.user_id != user.id:
        return jsonify({'error': 'Not your booking', 'code': 'PERM_001'}), 403
    
    if booking.status not in ['booked', 'used']:
        return jsonify({'error': 'Booking cannot be cancelled', 'code': 'BUS_001'}), 409
    
    # Check 15-minute rule
    now = datetime.now()
    booking_start = datetime.strptime(f"{booking.date} {booking.start_time}", '%Y-%m-%d %H:%M')
    if now > booking_start - timedelta(minutes=15):
        return jsonify({'error': 'Cannot cancel within 15 minutes of start time', 'code': 'BUS_001'}), 409
    
    booking.status = 'cancelled'
    db_session.commit()
    
    return jsonify({'message': 'Booking cancelled successfully'})

@app.route('/api/bookings/<int:booking_id>/checkin', methods=['POST'])
@token_required
def checkin_booking(user, booking_id):
    booking = db_session.query(Booking).get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found', 'code': 'RES_001'}), 404
    
    if booking.user_id != user.id:
        return jsonify({'error': 'Not your booking', 'code': 'PERM_001'}), 403
    
    if booking.status != 'booked':
        return jsonify({'error': 'Booking cannot be checked in', 'code': 'BUS_001'}), 409
    
    now = datetime.now()
    booking_start = datetime.strptime(f"{booking.date} {booking.start_time}", '%Y-%m-%d %H:%M')
    booking_end = datetime.strptime(f"{booking.date} {booking.end_time}", '%Y-%m-%d %H:%M')
    
    if now < booking_start:
        return jsonify({'error': 'Cannot check in before start time', 'code': 'BUS_001'}), 409
    
    if now > booking_start + timedelta(minutes=15):
        return jsonify({'error': 'Too late to check in', 'code': 'BUS_001'}), 409
    
    booking.status = 'used'
    booking.check_in_time = now
    db_session.commit()
    
    return jsonify({'message': 'Check-in successful', 'booking_id': booking.id})

# Admin routes
@app.route('/api/admin/violations', methods=['GET'])
@token_required
@admin_required
def get_violations(user):
    process_violations()
    violations = db_session.query(Booking).filter_by(status='violated').order_by(Booking.date.desc()).all()
    
    violation_list = []
    for v in violations:
        violator = db_session.query(User).get(v.user_id)
        seat = db_session.query(Seat).get(v.seat_id)
        violation_list.append({
            'id': v.id,
            'user_id': v.user_id,
            'username': violator.username if violator else 'Unknown',
            'seat_number': seat.seat_number if seat else 'Unknown',
            'date': v.date,
            'start_time': v.start_time,
            'end_time': v.end_time,
            'violation_count': violator.violation_count if violator else 0
        })
    
    return jsonify({'violations': violation_list})

@app.route('/api/admin/blacklist', methods=['GET', 'POST'])
@token_required
@admin_required
def manage_blacklist(user):
    if request.method == 'GET':
        blacklisted = db_session.query(User).filter_by(is_blacklisted=True).all()
        return jsonify({
            'blacklisted_users': [{
                'id': u.id,
                'username': u.username,
                'violation_count': u.violation_count,
                'created_at': u.created_at.isoformat() if u.created_at else None
            } for u in blacklisted]
        })
    
    elif request.method == 'POST':
        data = request.get_json()
        if not data or not data.get('user_id'):
            return jsonify({'error': 'Missing user_id', 'code': 'PARAM_001', 'details': ['user_id required']}), 400
        
        target_user = db_session.query(User).get(data['user_id'])
        if not target_user:
            return jsonify({'error': 'User not found', 'code': 'RES_001'}), 404
        
        target_user.is_blacklisted = True
        db_session.commit()
        
        return jsonify({'message': 'User blacklisted', 'user_id': target_user.id, 'username': target_user.username})

@app.route('/api/admin/blacklist/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def remove_from_blacklist(user, user_id):
    target_user = db_session.query(User).get(user_id)
    if not target_user:
        return jsonify({'error': 'User not found', 'code': 'RES_001'}), 404
    
    target_user.is_blacklisted = False
    target_user.violation_count = 0
    db_session.commit()
    
    return jsonify({'message': 'User removed from blacklist', 'user_id': target_user.id})

@app.route('/api/admin/bookings', methods=['GET'])
@token_required
@admin_required
def get_all_bookings(user):
    process_violations()
    bookings = db_session.query(Booking).order_by(Booking.date.desc(), Booking.start_time).all()
    
    booking_list = []
    for booking in bookings:
        booker = db_session.query(User).get(booking.user_id)
        seat = db_session.query(Seat).get(booking.seat_id)
        booking_list.append({
            'id': booking.id,
            'user_id': booking.user_id,
            'username': booker.username if booker else 'Unknown',
            'seat_id': booking.seat_id,
            'seat_number': seat.seat_number if seat else 'Unknown',
            'date': booking.date,
            'start_time': booking.start_time,
            'end_time': booking.end_time,
            'status': booking.status,
            'companion_ids': booking.companion_ids,
            'check_in_time': booking.check_in_time.isoformat() if booking.check_in_time else None
        })
    
    return jsonify({'bookings': booking_list})

@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def get_all_users(user):
    users = db_session.query(User).all()
    return jsonify({
        'users': [{
            'id': u.id,
            'username': u.username,
            'role': u.role,
            'violation_count': u.violation_count,
            'is_blacklisted': u.is_blacklisted,
            'created_at': u.created_at.isoformat() if u.created_at else None
        } for u in users]
    })

@app.route('/api/admin/seats', methods=['POST'])
@token_required
@admin_required
def create_seat(user):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing data', 'code': 'PARAM_001', 'details': ['Request body required']}), 400
    
    seat_number = data.get('seat_number')
    seat_type = data.get('type', 'single')
    capacity = data.get('capacity', 1)
    has_power = data.get('has_power', False)
    location = data.get('location', '')
    
    if not seat_number:
        return jsonify({'error': 'Missing seat_number', 'code': 'PARAM_001', 'details': ['seat_number required']}), 400
    
    if seat_type not in ['single', 'meeting']:
        return jsonify({'error': 'Invalid seat type', 'code': 'PARAM_001', 'details': ['Type must be single or meeting']}), 400
    
    existing = db_session.query(Seat).filter_by(seat_number=seat_number).first()
    if existing:
        return jsonify({'error': 'Seat number already exists', 'code': 'BUS_001'}), 409
    
    seat = Seat(
        seat_number=seat_number,
        type=seat_type,
        capacity=capacity,
        has_power=has_power,
        location=location,
        is_active=True
    )
    db_session.add(seat)
    db_session.commit()
    
    return jsonify({
        'seat': {
            'id': seat.id,
            'seat_number': seat.seat_number,
            'type': seat.type,
            'capacity': seat.capacity,
            'has_power': seat.has_power,
            'location': seat.location,
            'is_active': seat.is_active
        }
    }), 201

@app.route('/api/admin/bookings/<int:booking_id>/flag-empty', methods=['POST'])
@token_required
@admin_required
def flag_empty_seat(user, booking_id):
    booking = db_session.query(Booking).get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found', 'code': 'RES_001'}), 404
    
    if booking.status != 'used':
        return jsonify({'error': 'Only used bookings can be flagged', 'code': 'BUS_001'}), 409
    
    booker = db_session.query(User).get(booking.user_id)
    if not booker:
        return jsonify({'error': 'User not found', 'code': 'RES_001'}), 404
    
    booking.status = 'violated'
    booker.violation_count += 1
    
    if booker.violation_count >= 3:
        booker.is_blacklisted = True
    
    db_session.commit()
    
    return jsonify({
        'message': 'Empty seat occupation flagged',
        'booking': {
            'id': booking.id,
            'status': booking.status
        },
        'user': {
            'id': booker.id,
            'username': booker.username,
            'violation_count': booker.violation_count,
            'is_blacklisted': booker.is_blacklisted
        }
    })

# Initialize database with sample data
def init_db():
    """Idempotent seed.

    Each insert is committed individually with IntegrityError swallowed,
    so concurrent gunicorn workers calling init_db() in parallel cannot
    deadlock on UNIQUE constraint violations.
    """
    from sqlalchemy.exc import IntegrityError

    def _add_if_missing(query_filter, build):
        if db_session.query(query_filter[0]).filter_by(**query_filter[1]).first():
            return
        db_session.add(build())
        try:
            db_session.commit()
        except IntegrityError:
            db_session.rollback()  # another worker beat us to it - that is fine

    _add_if_missing(
        (User, {'username': 'admin'}),
        lambda: User(username='admin', password_hash=generate_password_hash('admin123'), role='admin'),
    )
    _add_if_missing(
        (User, {'username': 'student1'}),
        lambda: User(username='student1', password_hash=generate_password_hash('student123'), role='user'),
    )

    seat_numbers = ['A101', 'A102', 'A103', 'A104', 'A105', 'A106', 'A107', 'A108', 'A109', 'A110',
                    'B201', 'B202', 'B203', 'B204', 'B205']
    meeting_rooms = ['M301', 'M302', 'M303', 'M304', 'M305']

    for sn in seat_numbers:
        _add_if_missing(
            (Seat, {'seat_number': sn}),
            lambda sn=sn: Seat(seat_number=sn, type='single', capacity=1, has_power=True, location=f'Floor {sn[0]}'),
        )
    for mr in meeting_rooms:
        _add_if_missing(
            (Seat, {'seat_number': mr}),
            lambda mr=mr: Seat(seat_number=mr, type='meeting', capacity=6, has_power=True, location=f'Floor {mr[0]}'),
        )

# Initialize database
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)