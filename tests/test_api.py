import pytest
import json
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash
from app import app, engine, Base, User, Seat, Booking
import app as app_module

# Override the module-level Session for test isolation
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh in-memory database and seed data for each test."""
    test_engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine)()
    
    # Override the app's Session
    app_module.Session = test_session
    
    # Seed users
    admin = User(
        username='admin',
        password_hash=generate_password_hash('admin123'),
        role='admin',
        violation_count=0,
        is_blacklisted=False
    )
    testuser = User(
        username='testuser',
        password_hash=generate_password_hash('test123'),
        role='user',
        violation_count=0,
        is_blacklisted=False
    )
    test_session.add_all([admin, testuser])
    
    # Seed seats
    seat_single = Seat(
        seat_number='A101',
        type='single',
        capacity=1,
        has_power=True,
        location='Floor 1',
        is_active=True
    )
    seat_meeting = Seat(
        seat_number='M301',
        type='meeting',
        capacity=4,
        has_power=True,
        location='Floor 3',
        is_active=True
    )
    test_session.add_all([seat_single, seat_meeting])
    test_session.commit()
    
    yield test_session
    
    test_session.close()
    Base.metadata.drop_all(test_engine)

def get_seat_id(session, seat_number):
    """Helper to get seat id by seat number."""
    seat = session.query(Seat).filter(Seat.seat_number == seat_number).first()
    return seat.id if seat else None

def get_user_token(client, username, password):
    """Helper to login and get JWT token."""
    response = client.post('/api/login', json={
        'username': username,
        'password': password
    })
    if response.status_code == 200:
        return response.json['token']
    return None

def test_register_success(client, setup_db):
    """T1: Successful user registration."""
    response = client.post('/api/register', json={
        'username': 'newuser',
        'password': 'password123'
    })
    assert response.status_code == 201
    data = response.json
    assert 'token' in data
    assert data['user']['username'] == 'newuser'
    assert data['user']['role'] == 'user'

def test_register_duplicate_username(client, setup_db):
    """T2: Duplicate username returns 409 BUS_001."""
    response = client.post('/api/register', json={
        'username': 'testuser',
        'password': 'password123'
    })
    assert response.status_code == 409
    assert response.json['code'] == 'BUS_001'

def test_register_short_password(client, setup_db):
    """T3: Password too short returns 400 PARAM_001."""
    response = client.post('/api/register', json={
        'username': 'anotheruser',
        'password': '12345'
    })
    assert response.status_code == 400
    assert response.json['code'] == 'PARAM_001'

def test_login_success(client, setup_db):
    """T4: Successful login returns token and user info."""
    response = client.post('/api/login', json={
        'username': 'testuser',
        'password': 'test123'
    })
    assert response.status_code == 200
    data = response.json
    assert 'token' in data
    assert data['user']['username'] == 'testuser'
    assert data['user']['role'] == 'user'

def test_login_wrong_password(client, setup_db):
    """T5: Wrong password returns 401 AUTH_001."""
    response = client.post('/api/login', json={
        'username': 'testuser',
        'password': 'wrongpassword'
    })
    assert response.status_code == 401
    assert response.json['code'] == 'AUTH_001'

def test_login_blacklisted_user(client, setup_db):
    """T6: Blacklisted user cannot login (403 PERM_001)."""
    # First blacklist the user
    admin_token = get_user_token(client, 'admin', 'admin123')
    client.post('/api/admin/blacklist/add', 
                json={'username': 'testuser'},
                headers={'Authorization': f'Bearer {admin_token}'})
    
    # Now try to login
    response = client.post('/api/login', json={
        'username': 'testuser',
        'password': 'test123'
    })
    assert response.status_code == 403
    assert response.json['code'] == 'PERM_001'

def test_unauthenticated_booking(client, setup_db):
    """T7: Booking without token returns 401 AUTH_001 (FR-01)."""
    response = client.post('/api/bookings', json={
        'seat_id': 1,
        'date': '2026-12-15',
        'start_time': '09:00',
        'end_time': '10:00'
    })
    assert response.status_code == 401
    assert response.json['code'] == 'AUTH_001'

def test_duration_over_60min_rejected(client, setup_db):
    """T8: Booking duration > 60 minutes returns 400 PARAM_001 (FR-02)."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:30'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 400
    assert response.json['code'] == 'PARAM_001'

def test_booking_conflict_detection(client, setup_db):
    """T9: Conflicting booking returns 409 BUS_001 (FR-03)."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    # First booking
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 201
    
    # Second booking - same seat, overlapping time
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:30',
            'end_time': '10:30'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 409
    assert response.json['code'] == 'BUS_001'

def test_cancel_within_15min_rejected(client, setup_db):
    """T10: Cancelling within 15 minutes of start returns 409 BUS_001 (FR-04)."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    # Create a booking starting in 5 minutes
    now = datetime.now()
    start_time = (now + timedelta(minutes=5)).strftime('%H:%M')
    end_time = (now + timedelta(minutes=65)).strftime('%H:%M')
    
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': now.strftime('%Y-%m-%d'),
            'start_time': start_time,
            'end_time': end_time
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 201
    booking_id = response.json['booking']['id']
    
    # Try to cancel
    response = client.delete(f'/api/bookings/{booking_id}',
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 409
    assert response.json['code'] == 'BUS_001'

def test_one_active_booking_per_user(client, setup_db):
    """T11: User cannot have more than one active booking (FR-05)."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id_1 = get_seat_id(setup_db, 'A101')
    seat_id_2 = get_seat_id(setup_db, 'M301')
    
    # First booking
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id_1,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 201
    
    # Second booking - should fail
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id_2,
            'date': '2026-12-15',
            'start_time': '10:00',
            'end_time': '11:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 409
    assert response.json['code'] == 'BUS_001'

def test_meeting_room_requires_companions(client, setup_db):
    """T12: Meeting room booking requires companion IDs (FR-06)."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'M301')
    
    # Booking meeting room without companions
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 400
    assert response.json['code'] == 'PARAM_001'

def test_admin_only_endpoints_reject_user(client, setup_db):
    """T13: Regular user cannot access admin endpoints (FR-08)."""
    token = get_user_token(client, 'testuser', 'test123')
    
    # Try to view all bookings
    response = client.get('/api/admin/bookings',
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 403
    assert response.json['code'] == 'PERM_001'
    
    # Try to manage blacklist
    response = client.post('/api/admin/blacklist/add',
        json={'username': 'testuser'},
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 403
    assert response.json['code'] == 'PERM_001'

def test_admin_blacklist_add_remove(client, setup_db):
    """T14: Admin can add and remove users from blacklist (FR-10)."""
    admin_token = get_user_token(client, 'admin', 'admin123')
    
    # Add to blacklist
    response = client.post('/api/admin/blacklist/add',
        json={'username': 'testuser'},
        headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 200
    
    # Verify user is blacklisted
    user = setup_db.query(User).filter(User.username == 'testuser').first()
    assert user.is_blacklisted == True
    
    # Remove from blacklist
    response = client.post('/api/admin/blacklist/remove',
        json={'username': 'testuser'},
        headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 200
    
    # Verify user is no longer blacklisted
    user = setup_db.query(User).filter(User.username == 'testuser').first()
    assert user.is_blacklisted == False

def test_unified_error_format_all_codes(client, setup_db):
    """T15: All error responses have unified format with code field."""
    # Test AUTH_001
    response = client.get('/api/bookings')
    assert 'code' in response.json
    assert response.json['code'] == 'AUTH_001'
    
    # Test PERM_001
    token = get_user_token(client, 'testuser', 'test123')
    response = client.get('/api/admin/bookings',
        headers={'Authorization': f'Bearer {token}'})
    assert response.json['code'] == 'PERM_001'
    
    # Test PARAM_001
    response = client.post('/api/register', json={'username': 'test'})
    assert response.json['code'] == 'PARAM_001'
    
    # Test BUS_001
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    client.post('/api/bookings', 
        json={'seat_id': seat_id, 'date': '2026-12-15', 'start_time': '09:00', 'end_time': '10:00'},
        headers={'Authorization': f'Bearer {token}'})
    response = client.post('/api/bookings', 
        json={'seat_id': seat_id, 'date': '2026-12-15', 'start_time': '09:00', 'end_time': '10:00'},
        headers={'Authorization': f'Bearer {token}'})
    assert response.json['code'] == 'BUS_001'
    
    # Test RES_001 (resource not found)
    response = client.delete('/api/bookings/99999',
        headers={'Authorization': f'Bearer {token}'})
    assert response.json['code'] == 'RES_001'
    
    # Test SYS_001 (system error - invalid JSON)
    response = client.post('/api/login', data='invalid json',
        content_type='application/json')
    assert response.json['code'] == 'SYS_001'

def test_booking_success(client, setup_db):
    """Additional test: Successful booking flow."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 201
    data = response.json
    assert 'booking' in data
    assert data['booking']['status'] == 'booked'

def test_checkin_success(client, setup_db):
    """Additional test: Successful check-in."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    # Create booking for future
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    booking_id = response.json['booking']['id']
    
    # Check in
    response = client.post(f'/api/bookings/{booking_id}/checkin',
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    assert response.json['booking']['status'] == 'used'

def test_cancel_booking_success(client, setup_db):
    """Additional test: Successful cancellation."""
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    # Create booking for future
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    booking_id = response.json['booking']['id']
    
    # Cancel
    response = client.delete(f'/api/bookings/{booking_id}',
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    assert response.json['booking']['status'] == 'cancelled'

def test_admin_view_all_bookings(client, setup_db):
    """Additional test: Admin can view all bookings."""
    admin_token = get_user_token(client, 'admin', 'admin123')
    
    response = client.get('/api/admin/bookings',
        headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 200
    assert 'bookings' in response.json

def test_seat_status_view(client, setup_db):
    """Additional test: View seat real-time status (FR-09)."""
    token = get_user_token(client, 'testuser', 'test123')
    
    response = client.get('/api/seats/status',
        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    assert 'seats' in response.json

def test_violation_auto_blacklist(client, setup_db):
    """Additional test: 3 violations auto-blacklist (FR-07)."""
    admin_token = get_user_token(client, 'admin', 'admin123')
    
    # Set violation count to 2
    user = setup_db.query(User).filter(User.username == 'testuser').first()
    user.violation_count = 2
    setup_db.commit()
    
    # Flag a booking as empty-seat-occupation (FR-11)
    token = get_user_token(client, 'testuser', 'test123')
    seat_id = get_seat_id(setup_db, 'A101')
    
    # Create and check in a booking
    response = client.post('/api/bookings', 
        json={
            'seat_id': seat_id,
            'date': '2026-12-15',
            'start_time': '09:00',
            'end_time': '10:00'
        },
        headers={'Authorization': f'Bearer {token}'})
    booking_id = response.json['booking']['id']
    
    # Admin flags as empty-seat-occupation
    response = client.post(f'/api/admin/bookings/{booking_id}/flag-empty',
        headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 200
    
    # Verify user is now blacklisted
    user = setup_db.query(User).filter(User.username == 'testuser').first()
    assert user.is_blacklisted == True
    assert user.violation_count == 3