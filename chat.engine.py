import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
import sqlite3
from datetime import datetime, timedelta
import uuid
import json
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.secret_key = os.urandom(24)  # Secure secret key
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'wav', 'mp3', 'ogg', 'webm'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize flask-limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Database setup
def init_db():
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    
    # Check if tables exist before creating them
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not c.fetchone():
        c.execute('''CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE,
            role TEXT NOT NULL CHECK(role IN ('student', 'teacher', 'parent', 'admin')),
            approved BOOLEAN DEFAULT FALSE,
            banned BOOLEAN DEFAULT FALSE,
            ban_reason TEXT,
            banned_at DATETIME,
            banned_by INTEGER,
            reset_token TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME,
            is_online BOOLEAN DEFAULT FALSE,
            profile_picture TEXT DEFAULT 'default.png',
            FOREIGN KEY (banned_by) REFERENCES users(id)
        )''')
    
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    if not c.fetchone():
        c.execute('''CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            username TEXT NOT NULL,
            message TEXT NOT NULL,
            message_type TEXT DEFAULT 'text',
            file_path TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_edited BOOLEAN DEFAULT FALSE,
            edited_at DATETIME,
            reply_to INTEGER,
            FOREIGN KEY (reply_to) REFERENCES messages(id)
        )''')
    
    # Create rooms table for better room management
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rooms'")
    if not c.fetchone():
        c.execute('''CREATE TABLE rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            allowed_roles TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
    
    # Create user_settings table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'")
    if not c.fetchone():
        c.execute('''CREATE TABLE user_settings (
            user_id INTEGER PRIMARY KEY,
            theme TEXT DEFAULT 'dark',
            notifications BOOLEAN DEFAULT TRUE,
            sound_effects BOOLEAN DEFAULT TRUE,
            font_size INTEGER DEFAULT 14,
            auto_login BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )''')
    
    # Insert default rooms if they don't exist
    default_rooms = [
        ('general', 'General discussion room', '["student", "teacher", "parent", "admin"]', 'system'),
        ('teachers_students', 'Teacher-Student discussions', '["teacher", "student"]', 'system'),
        ('parents_teachers', 'Parent-Teacher discussions', '["parent", "teacher"]', 'system'),
        ('admin', 'Administrative discussions', '["admin"]', 'system')
    ]
    
    for room in default_rooms:
        c.execute("SELECT id FROM rooms WHERE name = ?", (room[0],))
        if not c.fetchone():
            c.execute("INSERT INTO rooms (name, description, allowed_roles, created_by) VALUES (?, ?, ?, ?)", room)
    
    # Check if approved column exists in users table
    try:
        c.execute("SELECT approved FROM users LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, so add it
        c.execute("ALTER TABLE users ADD COLUMN approved BOOLEAN DEFAULT FALSE")
        # Auto-approve existing users
        c.execute("UPDATE users SET approved = TRUE WHERE approved IS FALSE")
    
    # Check if banned columns exist in users table
    try:
        c.execute("SELECT banned, ban_reason, banned_at, banned_by FROM users LIMIT 1")
    except sqlite3.OperationalError:
        # Columns don't exist, so add them
        c.execute("ALTER TABLE users ADD COLUMN banned BOOLEAN DEFAULT FALSE")
        c.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
        c.execute("ALTER TABLE users ADD COLUMN banned_at DATETIME")
        c.execute("ALTER TABLE users ADD COLUMN banned_by INTEGER")
    
    conn.commit()
    conn.close()

init_db()

# Decorator for login required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Decorator for role-based access
def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login', next=request.url))
            if session.get('role') not in roles:
                return "Access denied", 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Decorator for approval and ban check
def approval_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        c.execute("SELECT approved, banned FROM users WHERE id = ?", (session['user_id'],))
        user = c.fetchone()
        conn.close()
        
        if not user:
            session.clear()
            return redirect(url_for('login'))
        
        if not user[0]:  # Not approved
            return "Your account is pending admin approval. Please wait.", 403
        
        if user[1]:  # Banned
            # Get ban details
            conn = sqlite3.connect('chatdatabase.db')
            c = conn.cursor()
            c.execute("SELECT ban_reason FROM users WHERE id = ?", (session['user_id'],))
            ban_reason = c.fetchone()[0] or "No reason provided"
            conn.close()
            
            session.clear()
            return f"Your account has been banned. Reason: {ban_reason}", 403
        
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember_me = 'remember_me' in request.form
        
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
        user = c.fetchone()
        
        if user:
            # Check if user is approved (index 5 is the approved column)
            if not user[5]:
                conn.close()
                return render_template('login.html', error="Account pending admin approval. Please wait.")
            
            # Check if user is banned (index 6 is the banned column)
            if user[6]:
                # Get ban details
                c.execute("SELECT ban_reason FROM users WHERE id = ?", (user[0],))
                ban_details = c.fetchone()
                ban_reason = ban_details[0] if ban_details else "No reason provided"
                conn.close()
                return render_template('login.html', error=f"Account banned. Reason: {ban_reason}")
            
            session['username'] = user[1]
            session['role'] = user[4]
            session['user_id'] = user[0]
            
            if remember_me:
                session.permanent = True
            
            # Update last login and online status
            c.execute("UPDATE users SET last_login = ?, is_online = TRUE WHERE id = ?", 
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user[0]))
            conn.commit()
            
            # Initialize user settings if they don't exist
            c.execute("SELECT * FROM user_settings WHERE user_id = ?", (user[0],))
            if not c.fetchone():
                c.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user[0],))
                conn.commit()
            
            conn.close()
            
            # Redirect to next page if provided, otherwise to chat
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('chat'))
        
        conn.close()
        return render_template('login.html', error="Invalid credentials")
    
    return render_template('login.html')

@app.route('/verify_linkvertise')
def verify_linkvertise():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id parameter'}), 400
    
    session['linkvertise_task_completed'] = True
    session['linkvertise_user_id'] = user_id
    print(f"Linkvertise task completed for user_id: {user_id}")
    
    return render_template('task_complete.html')

@app.route('/check_task_completion')
@limiter.limit("30 per minute")  # Increased to allow more frequent polling
def check_task_completion():
    user_id = request.args.get('user_id')
    task_completed = session.get('linkvertise_task_completed', False) and session.get('linkvertise_user_id') == user_id
    print(f"Checking task completion for user_id: {user_id}, completed: {task_completed}")
    return jsonify({'task_completed': task_completed}), 200

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not session.get('linkvertise_task_completed', False):
            return render_template('register.html', error='Please complete the verification task before registering.')
        
        username = request.form['username']
        email = request.form.get('email', '')
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form['role']
        
        if password != confirm_password:
            return render_template('register.html', error='Passwords do not match.')
        
        if role not in ['student', 'teacher', 'parent', 'admin']:
            return render_template('register.html', error='Invalid role selected.')
        
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        if c.fetchone():
            conn.close()
            return render_template('register.html', error='Username already exists.')
        
        hashed_password = generate_password_hash(password)
        c.execute("INSERT INTO users (username, email, password, role, approved, banned) VALUES (?, ?, ?, ?, ?, ?)",
                 (username, email, hashed_password, role, False, False))
        conn.commit()
        conn.close()
        
        session.pop('linkvertise_task_completed', None)
        session.pop('linkvertise_user_id', None)
        
        flash('Registration successful! Awaiting admin approval.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        
        if user:
            reset_token = str(uuid.uuid4())
            c.execute("UPDATE users SET reset_token = ? WHERE username = ?", (reset_token, username))
            conn.commit()
            conn.close()
            
            # In a real application, you would send an email here
            return render_template('forgot_password.html', 
                                 success=f"Reset token generated: {reset_token}. Use it to update your password.")
        
        conn.close()
        return render_template('forgot_password.html', error="Username not found")
    
    return render_template('forgot_password.html')

@app.route('/update_password', methods=['GET', 'POST'])
def update_password():
    if request.method == 'POST':
        if 'username' in session:
            # Logged-in user updating password
            username = session['username']
            new_password = request.form['new_password']
            confirm_password = request.form['confirm_password']
            
            if new_password != confirm_password:
                return render_template('update_password.html', error="Passwords do not match")
            
            conn = sqlite3.connect('chatdatabase.db')
            c = conn.cursor()
            c.execute("UPDATE users SET password = ?, reset_token = NULL WHERE username = ?", 
                     (new_password, username))
            conn.commit()
            conn.close()
            return render_template('update_password.html', success="Password updated successfully")
        else:
            # Password reset via token
            token = request.form['reset_token']
            new_password = request.form['new_password']
            confirm_password = request.form['confirm_password']
            
            if new_password != confirm_password:
                return render_template('update_password.html', error="Passwords do not match")
            
            conn = sqlite3.connect('chatdatabase.db')
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE reset_token = ?", (token,))
            user = c.fetchone()
            
            if user:
                c.execute("UPDATE users SET password = ?, reset_token = NULL WHERE reset_token = ?", 
                         (new_password, token))
                conn.commit()
                conn.close()
                return render_template('update_password.html', success="Password reset successfully. Please login.")
            
            conn.close()
            return render_template('update_password.html', error="Invalid or expired reset token")
    
    return render_template('update_password.html')

@app.route('/chat')
@login_required
@approval_required
def chat():
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    
    # Get available rooms for the user's role
    c.execute("SELECT name, description FROM rooms WHERE is_active = TRUE")
    all_rooms = c.fetchall()
    
    available_rooms = []
    for room in all_rooms:
        available_rooms.append({'name': room[0], 'description': room[1]})
    
    # Get user settings
    c.execute("SELECT theme, notifications, sound_effects, font_size, auto_login FROM user_settings WHERE user_id = ?", 
             (session['user_id'],))
    settings_row = c.fetchone()
    
    conn.close()
    
    # Convert settings to a proper dictionary
    settings = {}
    if settings_row:
        settings = {
            'theme': settings_row[0],
            'notifications': bool(settings_row[1]),
            'sound_effects': bool(settings_row[2]),
            'font_size': settings_row[3],
            'auto_login': bool(settings_row[4])
        }
    
    return render_template('chat.html', 
                         username=session['username'], 
                         role=session['role'],
                         rooms=available_rooms,
                         settings=settings)

@app.route('/get_online_users')
@login_required
@approval_required
def get_online_users():
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    c.execute("SELECT username, role FROM users WHERE is_online = TRUE AND username != ?", (session['username'],))
    online_users = [{'username': row[0], 'role': row[1]} for row in c.fetchall()]
    conn.close()
    return jsonify(online_users)

@app.route('/send_message', methods=['POST'])
@login_required
@approval_required
def send_message():
    try:
        # Validate required form fields
        if 'room' not in request.form:
            print("Error: Missing 'room' field in request")
            return jsonify({'error': 'Room parameter is required'}), 400
        
        room = request.form['room']
        message_type = request.form.get('message_type', 'text')
        
        print(f"Received message for room: {room}, type: {message_type}")
        print(f"Request form data: {dict(request.form)}")
        print(f"Request files: {request.files}")
        
        # Validate message content for text messages
        message_content = request.form.get('message', '')
        if message_type == 'text' and not message_content.strip():
            print("Error: Text message is empty")
            return jsonify({'error': 'Text message cannot be empty'}), 400
        
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        c.execute("SELECT allowed_roles FROM rooms WHERE name = ?", (room,))
        room_data = c.fetchone()
        
        if not room_data:
            conn.close()
            print("Room not found")
            return jsonify({'error': 'Room not found'}), 404
        
        # Check if user role is allowed
        allowed_roles = json.loads(room_data[0])
        if session['role'] not in allowed_roles:
            conn.close()
            print(f"Access denied: User role {session['role']} not allowed in room {room}")
            return jsonify({'error': 'Access denied to this room'}), 403
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Handle file upload
        file_path = None
        if 'file' in request.files:
            file = request.files['file']
            print(f"File received: filename={file.filename}, content_type={file.content_type}")
            if file and file.filename:
                # Extract extension from filename or content type
                filename = secure_filename(file.filename)
                extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                if not extension and file.content_type:
                    # Fallback to content type for extension
                    mime_to_ext = {
                        'image/png': 'png',
                        'image/jpeg': 'jpg',
                        'image/gif': 'gif',
                        'video/mp4': 'mp4',
                        'video/quicktime': 'mov',
                        'video/x-msvideo': 'avi',
                        'audio/mpeg': 'mp3',
                        'audio/wav': 'wav',
                        'audio/ogg': 'ogg'
                    }
                    extension = mime_to_ext.get(file.content_type, '')
                
                if extension in ALLOWED_EXTENSIONS:
                    filename = secure_filename(f"{session['user_id']}_{int(datetime.now().timestamp())}_{filename}")
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    file_path = f"/{file_path}"  # Store relative path starting with /
                    if message_type != 'text':
                        message_content = file_path
                    print(f"File saved: {file_path}")
                else:
                    conn.close()
                    print(f"Error: Invalid file extension '{extension}'")
                    return jsonify({'error': f"Invalid file extension. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
            else:
                conn.close()
                print("Error: No valid file provided")
                return jsonify({'error': 'No valid file provided'}), 400
        
        # Ensure there's content to save (either message or file)
        if not message_content and not file_path:
            conn.close()
            print("Error: No message content or file provided")
            return jsonify({'error': 'Message or file required'}), 400
        
        print(f"Inserting message: {message_content}")
        
        c.execute("INSERT INTO messages (room, username, message, message_type, file_path, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                 (room, session['username'], message_content, message_type, file_path, timestamp))
        message_id = c.lastrowid
        conn.commit()
        conn.close()
        
        print("Message inserted successfully")
        return jsonify({
            'status': 'success',
            'timestamp': timestamp,
            'file_path': file_path,
            'message_type': message_type,
            'message': message_content,
            'username': session['username'],
            'id': message_id
        })
        
    except Exception as e:
        print(f"Error in send_message: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/get_messages/<room>')
@login_required
@approval_required
def get_messages(room):
    limit = request.args.get('limit', 850)
    offset = request.args.get('offset', 0)
    
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    c.execute("""
        SELECT username, message, message_type, file_path, timestamp, is_edited, edited_at 
        FROM messages 
        WHERE room = ? 
        ORDER BY timestamp DESC 
        LIMIT ? OFFSET ?
    """, (room, limit, offset))
    
    messages = []
    for row in c.fetchall():
        messages.append({
            'username': row[0],
            'message': row[1],
            'message_type': row[2],
            'file_path': row[3],
            'timestamp': row[4],
            'is_edited': bool(row[5]),
            'edited_at': row[6]
        })
    
    conn.close()
    return jsonify(messages[::-1])  # Reverse to show oldest first

@app.route('/search_messages')
@login_required
@approval_required
def search_messages():
    query = request.args.get('q')
    room = request.args.get('room')
    
    if not query:
        return jsonify({'error': 'Query parameter required'}), 400
    
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    c.execute("""
        SELECT username, message, message_type, timestamp 
        FROM messages 
        WHERE room = ? AND message LIKE ? 
        ORDER BY timestamp DESC
    """, (room, f'%{query}%'))
    
    results = []
    for row in c.fetchall():
        results.append({
            'username': row[0],
            'message': row[1],
            'message_type': row[2],
            'timestamp': row[3]
        })
    
    conn.close()
    return jsonify(results)

@app.route('/user_settings', methods=['GET', 'POST'])
@login_required
@approval_required
def user_settings():
    if request.method == 'POST':
        theme = request.form.get('theme')
        notifications = 'notifications' in request.form
        sound_effects = 'sound_effects' in request.form
        font_size = request.form.get('font_size')
        auto_login = 'auto_login' in request.form
        
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        c.execute("""
            UPDATE user_settings 
            SET theme = ?, notifications = ?, sound_effects = ?, font_size = ?, auto_login = ?
            WHERE user_id = ?
        """, (theme, notifications, sound_effects, font_size, auto_login, session['user_id']))
        conn.commit()
        conn.close()
        
        flash('Settings saved successfully!')
        return redirect(url_for('user_settings'))
    
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    c.execute("SELECT theme, notifications, sound_effects, font_size, auto_login FROM user_settings WHERE user_id = ?", 
             (session['user_id'],))
    settings_row = c.fetchone()
    conn.close()
    
    # Convert settings to a proper dictionary
    settings = {}
    if settings_row:
        settings = {
            'theme': settings_row[0],
            'notifications': bool(settings_row[1]),
            'sound_effects': bool(settings_row[2]),
            'font_size': settings_row[3],
            'auto_login': bool(settings_row[4])
        }
    
    return render_template('user_settings.html', settings=settings)

@app.route('/logout')
def logout():
    if 'username' in session:
        # Update online status
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_online = FALSE WHERE username = ?", (session['username'],))
        conn.commit()
        conn.close()
    
    session.clear()
    flash('You have been logged out successfully.')
    return redirect(url_for('login'))

# Admin routes
# Simulated admin credentials (in production, use environment variables or secure config)
ADMIN_CREDENTIALS = {
    'superadmin1': {
        'password': 'LoveGod#kingno:1',  # Change this in production!
        'role': 'admin',
        'email': 'superadmin1@kgoloko.com'
    },
    'superadmin2': {
        'password': 'LoveGod@kingno:1',  # Change this in production!
        'role': 'admin', 
        'email': 'superadmin2@kgoloko.com'
    }
}

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember_me = 'remember_me' in request.form
        
        # Check against simulated admin credentials
        if username in ADMIN_CREDENTIALS and ADMIN_CREDENTIALS[username]['password'] == password:
            # Create or update admin user in database
            conn = sqlite3.connect('chatdatabase.db')
            c = conn.cursor()
            
            # Check if admin user exists in database
            c.execute("SELECT id, approved, banned FROM users WHERE username = ? AND role = 'admin'", (username,))
            existing_admin = c.fetchone()
            
            if existing_admin:
                user_id = existing_admin[0]
                # Check if admin is approved and not banned
                if not existing_admin[1] or existing_admin[2]:
                    conn.close()
                    return render_template('admin_login.html', error="Admin account is disabled. Please contact system administrator.")
            else:
                # Create new admin user in database
                try:
                    c.execute("INSERT INTO users (username, password, email, role, approved) VALUES (?, ?, ?, ?, ?)", 
                             (username, password, ADMIN_CREDENTIALS[username]['email'], 'admin', True))
                    conn.commit()
                    user_id = c.lastrowid
                    
                    # Create user settings
                    c.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
                    conn.commit()
                except sqlite3.IntegrityError:
                    conn.close()
                    return render_template('admin_login.html', error="Admin account creation failed.")
            
            # Set session variables
            session['username'] = username
            session['role'] = 'admin'
            session['user_id'] = user_id
            session['is_admin'] = True
            session['is_simulated_admin'] = True  # Flag to identify simulated admin
            
            if remember_me:
                session.permanent = True
            
            # Update last login and online status
            c.execute("UPDATE users SET last_login = ?, is_online = TRUE WHERE id = ?", 
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))
            conn.commit()
            conn.close()
            
            flash('Admin login successful!')
            return redirect(url_for('admin_users'))
        
        return render_template('admin_login.html', error="Invalid admin credentials")
    
    return render_template('admin_login.html')

@app.route('/admin/users')
@login_required
@role_required(['admin'])
def admin_users():
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    
    # Get all users with their approval and ban status
    c.execute("""
        SELECT id, username, email, role, approved, banned, ban_reason, created_at 
        FROM users 
        ORDER BY created_at DESC
    """)
    users = c.fetchall()
    
    conn.close()
    
    # Convert to list of dictionaries for easier template handling
    user_list = []
    for user in users:
        user_list.append({
            'id': user[0],
            'username': user[1],
            'email': user[2],
            'role': user[3],
            'approved': user[4],
            'banned': user[5],
            'ban_reason': user[6],
            'created_at': user[7]
        })
    
    return render_template('admin_users.html', users=user_list)

@app.route('/admin/approve_user/<int:user_id>')
@login_required
@role_required(['admin'])
def approve_user(user_id):
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    
    c.execute("UPDATE users SET approved = TRUE WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    flash('User approved successfully!')
    return redirect(url_for('admin_users'))

@app.route('/admin/reject_user/<int:user_id>')
@login_required
@role_required(['admin'])
def reject_user(user_id):
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    c.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    flash('User rejected and removed from system!')
    return redirect(url_for('admin_users'))

@app.route('/admin/ban_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
@role_required(['admin'])
def ban_user(user_id):
    if request.method == 'POST':
        ban_reason = request.form.get('ban_reason', 'No reason provided')
        
        conn = sqlite3.connect('chatdatabase.db')
        c = conn.cursor()
        
        # Ban the user
        c.execute("UPDATE users SET banned = TRUE, ban_reason = ?, banned_at = ?, banned_by = ? WHERE id = ?", 
                 (ban_reason, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['user_id'], user_id))
        
        # Set user offline if they're online
        c.execute("UPDATE users SET is_online = FALSE WHERE id = ?", (user_id,))
        
        conn.commit()
        
        # Get username for flash message
        c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
        username = c.fetchone()[0]
        
        conn.close()
        
        flash(f'User {username} has been banned successfully!')
        return redirect(url_for('admin_users'))
    
    # GET request - show ban form
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        flash('User not found!')
        return redirect(url_for('admin_users'))
    
    return render_template('ban_user.html', user={'id': user_id, 'username': user[0]})

@app.route('/static/uploads/<path:filename>')
def serve_uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    
@app.route('/admin/unban_user/<int:user_id>')
@login_required
@role_required(['admin'])
def unban_user(user_id):
    conn = sqlite3.connect('chatdatabase.db')
    c = conn.cursor()
    
    # Unban the user
    c.execute("UPDATE users SET banned = FALSE, ban_reason = NULL, banned_at = NULL, banned_by = NULL WHERE id = ?", 
             (user_id,))
    
    conn.commit()
    
    # Get username for flash message
    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    username = c.fetchone()[0]
    
    conn.close()
    
    flash(f'User {username} has been unbanned successfully!')
    return redirect(url_for('admin_users'))

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403
  
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)