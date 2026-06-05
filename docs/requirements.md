# Software Requirements Specification: University Library Seat Reservation System

## 1. System Scope

The University Library Seat Reservation System is a web-based application that enables students to reserve seats and meeting rooms in the university library. The system manages booking conflicts, enforces usage policies, tracks violations, and provides administrative oversight. It operates daily from 08:00 to 22:00, with bookings limited to 1-hour maximum duration per session.

**Key Capabilities:**
- User authentication and authorization (JWT-based)
- Seat and meeting room reservation with conflict detection
- Check-in enforcement with violation tracking
- Automated blacklisting for repeated violations
- Real-time seat availability display
- Administrative booking oversight and blacklist management

## 2. Actors

| Actor | Description | Primary Goals |
|-------|-------------|---------------|
| **Student (Regular User)** | University student with valid credentials | Browse seats, make/cancel bookings, check in, view own booking history |
| **Administrator** | Library staff with elevated privileges | View all bookings, manage blacklist, view violations, flag empty-seat-occupation |

## 3. Functional Requirements

### FR-01: User Authentication
**Priority:** High  
**Business Rule:** FR-01 (Users must login to book seats - JWT authentication)

Users must authenticate using their university credentials. The system issues a JWT token valid for the current session. All booking operations require a valid token.

### FR-02: Booking Duration Limit
**Priority:** High  
**Business Rule:** FR-02 (Each booking is maximum 1 hour)

Users select their desired duration (1 minute to 60 minutes). The system validates that the end time does not exceed the start time + 1 hour. Meeting rooms can be continuously booked (1-hour sessions, extendable if next time slot is free).

### FR-03: Conflict-Free Booking
**Priority:** High  
**Business Rule:** FR-03 (Booking time must not conflict - same seat, same time, only one person)

The system prevents double-booking by checking for overlapping time ranges on the same seat/room. Overlap occurs when:
- New start_time < existing end_time AND new end_time > existing start_time

### FR-04: Booking Cancellation
**Priority:** Medium  
**Business Rule:** FR-04 (Users can cancel bookings with >= 15 minutes advance notice)

Users can cancel their own bookings only if the current time is at least 15 minutes before the booking start time. Cancellations within 15 minutes of start time are prohibited.

### FR-05: Single Active Booking Per User
**Priority:** High  
**Business Rule:** FR-05 (One person can only have one active booking at a time)

The system checks that the user has no other bookings with status 'booked' or 'used' that overlap in time. A user cannot create a new booking while an existing active booking exists.

### FR-06: Seat Type Handling
**Priority:** Medium  
**Business Rule:** FR-06 (Seats are single seats or meeting rooms; meeting rooms require companion student IDs)

- **Single seats:** No companion IDs required
- **Meeting rooms:** User must provide comma-separated companion student IDs (minimum 1 companion). The system validates that companion IDs exist in the system.

### FR-07: Auto-Blacklisting
**Priority:** High  
**Business Rule:** FR-07 (3 or more violations = account auto-blacklisted for current month)

When a user's `violation_count` reaches 3 or more, the system automatically sets `is_blacklisted = true`. The blacklist resets at the start of each calendar month. Blacklisted users cannot create new bookings.

### FR-08: Administrator Booking View
**Priority:** Medium  
**Business Rule:** FR-08 (Administrator can view all bookings and real-time status)

Administrators can view a comprehensive list of all bookings across all users, including current status (booked/used/cancelled/violated), check-in times, and companion information.

### FR-09: Real-Time Seat Status
**Priority:** High  
**Business Rule:** FR-09 (Users can view seat real-time status displayed as timetable 08:00-22:00)

The system displays a timetable view for each seat showing occupied time slots (08:00-22:00). Available slots are shown as free. The display updates in real-time as bookings are made or cancelled.

### FR-10: Administrator Blacklist Management
**Priority:** Medium  
**Business Rule:** FR-10 (Administrator can manage blacklist - add/remove users manually)

Administrators can manually add users to the blacklist or remove them. Manual blacklisting increments the user's violation count by 1. Manual removal resets the violation count to 0.

### FR-11: Empty-Seat-Occupation Flagging
**Priority:** Medium  
**Business Rule:** FR-11 (Administrator can flag a "used" booking as empty-seat-occupation)

During patrol, administrators can flag a booking with status 'used' as empty-seat-occupation. This increments the user's `violation_count` by 1. If violation_count reaches 3, auto-blacklisting triggers (same as no-show penalty).

### Violation Logic Implementation

| Scenario | Action | Violation Count Impact |
|----------|--------|------------------------|
| User checks in on time | No violation | No change |
| User checks in >15 min late | System marks as violated | +1 |
| User never checks in | System marks as violated at +15 min | +1 |
| Admin flags empty-seat-occupation | System marks booking as violated | +1 |
| 3+ violations in month | Auto-blacklist | Set is_blacklisted=true |

## 4. Non-Functional Requirements

### Performance
- **Response Time:** All API endpoints must respond within 2 seconds under normal load (up to 500 concurrent users)
- **Real-Time Updates:** Seat status timetable must refresh within 1 second of any booking change
- **Concurrency:** Support at least 100 simultaneous booking operations

### Security
- **Authentication:** JWT tokens with 24-hour expiration; tokens must be sent in Authorization header
- **Password Storage:** bcrypt hashing with cost factor 12
- **Authorization:** Role-based access control (student vs. administrator)
- **Input Validation:** All user inputs must be sanitized to prevent injection attacks
- **Error Messages:** Unified error format: `{error, code, details}`

### Usability
- **Intuitive Interface:** Seat selection should be visual (timetable grid)
- **Feedback:** Clear success/error messages for all operations
- **Accessibility:** Support screen readers and keyboard navigation

### Reliability
- **Uptime:** 99.9% availability during library operating hours (08:00-22:00)
- **Data Integrity:** All booking transactions must be atomic (ACID compliant)
- **Backup:** Daily automated backups of all data

## 5. Data Entities

### User
| Attribute | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| id | UUID | PK, auto-generated | Unique user identifier |
| username | VARCHAR(50) | UNIQUE, NOT NULL | University login ID |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt hash of password |
| role | ENUM('user','admin') | NOT NULL, DEFAULT 'user' | User role |
| violation_count | INTEGER | NOT NULL, DEFAULT 0, >=0 | Current month violation count |
| is_blacklisted | BOOLEAN | NOT NULL, DEFAULT FALSE | Blacklist status |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Account creation timestamp |

### Seat
| Attribute | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| id | UUID | PK, auto-generated | Unique seat identifier |
| seat_number | VARCHAR(20) | UNIQUE, NOT NULL | Physical seat label |
| type | ENUM('single','meeting') | NOT NULL | Seat type |
| capacity | INTEGER | NOT NULL, >=1 | Maximum occupants (1 for single, 2+ for meeting) |
| has_power | BOOLEAN | NOT NULL, DEFAULT FALSE | Power outlet availability |
| location | VARCHAR(100) | NOT NULL | Floor/zone description |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | Whether seat is available for booking |

### Booking
| Attribute | Type | Constraints | Description |
|-----------|------|-------------|-------------|
| id | UUID | PK, auto-generated | Unique booking identifier |
| user_id | UUID | FK → User.id, NOT NULL | Booked by user |
| seat_id | UUID | FK → Seat.id, NOT NULL | Reserved seat |
| date | DATE | NOT NULL | Booking date |
| start_time | TIME | NOT NULL | Start time (08:00-21:00) |
| end_time | TIME | NOT NULL | End time (start_time + ≤1 hour, ≤22:00) |
| status | ENUM('booked','used','cancelled','violated') | NOT NULL, DEFAULT 'booked' | Current booking status |
| companion_ids | TEXT | NULL | Comma-separated student IDs (meeting rooms only) |
| check_in_time | TIMESTAMP | NULL | Actual check-in timestamp |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW() | Booking creation timestamp |

## 6. API Endpoints

### Authentication

#### POST /api/auth/login
**Auth:** None  
**Request:**
```json
{
  "username": "string",
  "password": "string"
}
```
**Response (200):**
```json
{
  "token": "jwt_token_string",
  "user": {
    "id": "uuid",
    "username": "string",
    "role": "user|admin"
  }
}
```
**Error Codes:** AUTH_001 (invalid credentials)

### User Endpoints

#### GET /api/seats
**Auth:** JWT Required  
**Description:** List all active seats with today's timetable  
**Response (200):**
```json
{
  "seats": [
    {
      "id": "uuid",
      "seat_number": "string",
      "type": "single|meeting",
      "capacity": 1,
      "has_power": true,
      "location": "string",
      "timetable": {
        "08:00": "available",
        "08:30": "booked",
        "09:00": "booked",
        ...
        "21:00": "available"
      }
    }
  ]
}
```

#### POST /api/bookings
**Auth:** JWT Required  
**Description:** Create a new booking  
**Request:**
```json
{
  "seat_id": "uuid",
  "date": "2024-01-15",
  "start_time": "10:00",
  "end_time": "11:00",
  "companion_ids": "student1,student2" // optional, for meeting rooms only
}
```
**Response (201):**
```json
{
  "booking_id": "uuid",
  "status": "booked",
  "message": "Booking confirmed"
}
```
**Error Codes:** AUTH_001, PARAM_001 (invalid time format), BUS_001 (conflict), BUS_002 (active booking exists), BUS_003 (blacklisted), RES_001 (seat not found)

#### DELETE /api/bookings/{booking_id}
**Auth:** JWT Required  
**Description:** Cancel own booking (≥15 min before start)  
**Response (200):**
```json
{
  "message": "Booking cancelled"
}
```
**Error Codes:** AUTH_001, PERM_001 (not owner), BUS_004 (too late to cancel), RES_001 (booking not found)

#### POST /api/bookings/{booking_id}/checkin
**Auth:** JWT Required  
**Description:** Simulate check-in for own booking  
**Response (200):**
```json
{
  "message": "Check-in successful",
  "status": "used"
}
```
**Error Codes:** AUTH_001, PERM_001 (not owner), BUS_005 (before start time), BUS_006 (already checked in), RES_001 (booking not found)

#### GET /api/users/me/bookings
**Auth:** JWT Required  
**Description:** Get current user's booking history  
**Response (200):**
```json
{
  "bookings": [
    {
      "id": "uuid",
      "seat_number": "string",
      "date": "2024-01-15",
      "start_time": "10:00",
      "end_time": "11:00",
      "status": "booked|used|cancelled|violated",
      "companion_ids": "string|null",
      "check_in_time": "timestamp|null"
    }
  ]
}
```

### Administrator Endpoints

#### GET /api/admin/bookings
**Auth:** JWT Required (admin role)  
**Description:** View all bookings with optional filters  
**Query Parameters:** `?date=2024-01-15&status=booked&user_id=uuid`  
**Response (200):**
```json
{
  "bookings": [
    {
      "id": "uuid",
      "user": {
        "id": "uuid",
        "username": "string"
      },
      "seat": {
        "id": "uuid",
        "seat_number": "string",
        "type": "single|meeting"
      },
      "date": "2024-01-15",
      "start_time": "10:00",
      "end_time": "11:00",
      "status": "booked|used|cancelled|violated",
      "companion_ids": "string|null",
      "check_in_time": "timestamp|null",
      "created_at": "timestamp"
    }
  ]
}
```
**Error Codes:** AUTH_001, PERM_001 (not admin)

#### GET /api/admin/blacklist
**Auth:** JWT Required (admin role)  
**Description:** View all blacklisted users  
**Response (200):**
```json
{
  "blacklisted_users": [
    {
      "id": "uuid",
      "username": "string",
      "violation_count": 3,
      "created_at": "timestamp"
    }
  ]
}
```

#### POST /api/admin/blacklist
**Auth:** JWT Required (admin role)  
**Description:** Manually add user to blacklist  
**Request:**
```json
{
  "user_id": "uuid"
}
```
**Response (200):**
```json
{
  "message": "User blacklisted",
  "violation_count": 3
}
```
**Error Codes:** AUTH_001, PERM_001, RES_001 (user not found), BUS_007 (already blacklisted)

#### DELETE /api/admin/blacklist/{user_id}
**Auth:** JWT Required (admin role)  
**Description:** Remove user from blacklist (resets violation count to 0)  
**Response (200):**
```json
{
  "message": "User removed from blacklist",
  "violation_count": 0
}
```
**Error Codes:** AUTH_001, PERM_001, RES_001 (user not found), BUS_008 (not blacklisted)

#### POST /api/admin/bookings/{booking_id}/flag-empty
**Auth:** JWT Required (admin role)  
**Description:** Flag a 'used' booking as empty-seat-occupation  
**Response (200):**
```json
{
  "message": "Empty-seat-occupation flagged",
  "violation_count": 2,
  "is_blacklisted": false
}
```
**Error Codes:** AUTH_001, PERM_001, RES_001 (booking not found), BUS_009 (booking not in 'used' status)

### Unified Error Format

All error responses follow this structure:
```json
{
  "error": {
    "code": "AUTH_001",
    "details": "Invalid username or password"
  }
}
```

| Code | Description | HTTP Status |
|------|-------------|-------------|
| AUTH_001 | Authentication failed | 401 |
| PERM_001 | Insufficient permissions | 403 |
| PARAM_001 | Invalid parameter format | 400 |
| BUS_001 | Booking conflict detected | 409 |
| BUS_002 | User has active booking | 409 |
| BUS_003 | User is blacklisted | 403 |
| BUS_004 | Cancellation too late | 400 |
| BUS_005 | Check-in before start time | 400 |
| BUS_006 | Already checked in | 409 |
| BUS_007 | Already blacklisted | 409 |
| BUS_008 | Not blacklisted | 400 |
| BUS_009 | Booking not in 'used' status | 400 |
| RES_001 | Resource not found | 404 |
| SYS_001 | Internal server error | 500 |