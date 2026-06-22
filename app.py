import os
import sqlite3
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)
app.secret_key = 'super_secret_session_key_for_tuition_system'
app.config['DATABASE'] = 'tuition_system.db'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max upload

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Database Helper Functions ---
def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as conn:
        # Admins Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        # Settings Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tuition_name TEXT NOT NULL,
                tuition_logo TEXT,
                theme_mode TEXT DEFAULT 'dark'
            )
        ''')
        # Students Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                mobile TEXT NOT NULL,
                father_name TEXT,
                mother_name TEXT,
                class TEXT,
                school_name TEXT,
                address TEXT,
                dob TEXT,
                admission_date TEXT,
                photo TEXT
            )
        ''')
        # Results Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                exam_name TEXT NOT NULL,
                total_marks REAL NOT NULL,
                obtained_marks REAL NOT NULL,
                percentage REAL NOT NULL,
                grade TEXT NOT NULL,
                exam_date TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')
        
        # Seed Default Admin if not exists
        admin_exists = conn.execute('SELECT * FROM admins WHERE username = ?', ('admin',)).fetchone()
        if not admin_exists:
            hashed_pw = generate_password_hash('admin123')
            conn.execute('INSERT INTO admins (username, password) VALUES (?, ?)', ('admin', hashed_pw))
            
        # Seed Default Settings if not exists
        settings_exists = conn.execute('SELECT * FROM settings LIMIT 1').fetchone()
        if not settings_exists:
            conn.execute('INSERT INTO settings (tuition_name, tuition_logo) VALUES (?, ?)', ('𝔼𝕡𝕤𝕚𝕝𝕠𝕟『𝜀』', 'default_logo.png'))
        
        conn.commit()

# Initialize DB on Startup
init_db()

# --- Context Processor for Global Settings ---
@app.context_processor
def inject_settings():
    conn = get_db()
    settings_row = conn.execute('SELECT * FROM settings LIMIT 1').fetchone()
    conn.close()
    return dict(system_settings=settings_row)

# --- Authentication Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Helper Logic for Grade & Percentage ---
def calculate_grade(obtained, total):
    if total <= 0: return 0, 'F'
    percentage = round((obtained / total) * 100, 2)
    if percentage >= 90: grade = 'A+'
    elif percentage >= 80: grade = 'A'
    elif percentage >= 70: grade = 'B+'
    elif percentage >= 60: grade = 'B'
    elif percentage >= 50: grade = 'C'
    elif percentage >= 40: grade = 'D'
    else: grade = 'F'
    return percentage, grade

# --- Routes ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'admin_logged_in' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        
        conn = get_db()
        admin = conn.execute('SELECT * FROM admins WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if admin and check_password_hash(admin['password'], password):
            session['admin_logged_in'] = True
            session['admin_username'] = admin['username']
            flash('Welcome back, Administrator!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    flash('You have logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    total_students = conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]
    total_classes = conn.execute('SELECT COUNT(DISTINCT class) FROM students WHERE class IS NOT NULL AND class != ""').fetchone()[0]
    total_results = conn.execute('SELECT COUNT(*) FROM results').fetchone()[0]
    
    recent_students = conn.execute('SELECT * FROM students ORDER BY id DESC LIMIT 5').fetchall()
    
    # Complex Query for Top Rankers across classes (based on average percentage)
    top_rankers = conn.execute('''
        SELECT s.name, s.class, s.mobile, ROUND(AVG(r.percentage), 2) as avg_pct 
        FROM students s 
        JOIN results r ON s.id = r.student_id 
        GROUP BY s.id 
        ORDER BY avg_pct DESC LIMIT 5
    ''').fetchall()
    
    conn.close()
    return render_template('dashboard.html', 
                           total_students=total_students, 
                           total_classes=total_classes, 
                           total_results=total_results,
                           recent_students=recent_students,
                           top_rankers=top_rankers)

@app.route('/students', methods=['GET', 'POST'])
@login_required
def students():
    conn = get_db()
    
    # Filters and Search
    search_query = request.args.get('search', '').strip()
    class_filter = request.args.get('class_filter', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    query = "SELECT * FROM students WHERE 1=1"
    params = []
    
    if search_query:
        query += " AND (name LIKE ? OR mobile LIKE ? OR student_id LIKE ?)"
        params.extend([f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'])
        
    if class_filter:
        query += " AND class = ?"
        params.append(class_filter)
        
    # Get total count for pagination
    count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
    total_records = conn.execute(count_query, params).fetchone()[0]
    total_pages = (total_records + per_page - 1) // per_page
    
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    
    student_list = conn.execute(query, params).fetchall()
    
    # Get all distinct classes for the filter dropdown
    classes = conn.execute('SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != "" ORDER BY class').fetchall()
    conn.close()
    
    return render_template('students.html', 
                           students=student_list, 
                           classes=classes, 
                           page=page, 
                           total_pages=total_pages,
                           search_query=search_query,
                           class_filter=class_filter)

@app.route('/student/add', methods=['POST'])
@login_required
def add_student():
    if request.method == 'POST':
        name = request.form.get('name').strip()
        mobile = request.form.get('mobile').strip()
        father_name = request.form.get('father_name').strip()
        mother_name = request.form.get('mother_name').strip()
        student_class = request.form.get('class').strip()
        school_name = request.form.get('school_name').strip()
        address = request.form.get('address').strip()
        dob = request.form.get('dob')
        admission_date = request.form.get('admission_date') or datetime.now().strftime('%Y-%m-%d')
        
        if not name or not mobile:
            flash('Student Name and Mobile Number are mandatory fields.', 'danger')
            return redirect(url_for('students'))
            
        # Handle Photo Upload
        photo_file = request.files.get('photo')
        filename = None
        if photo_file and photo_file.filename != '':
            filename = secure_filename(f"{int(datetime.now().timestamp())}_{photo_file.filename}")
            photo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
        conn = get_db()
        try:
            # Auto-generate unique Student ID
            current_year = datetime.now().strftime('%Y')
            last_id_row = conn.execute('SELECT id FROM students ORDER BY id DESC LIMIT 1').fetchone()
            next_serial = (last_id_row['id'] + 1) if last_id_row else 1
            student_id = f"TMS-{current_year}-{next_serial:04d}"
            
            conn.execute('''
                INSERT INTO students (student_id, name, mobile, father_name, mother_name, class, school_name, address, dob, admission_date, photo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (student_id, name, mobile, father_name, mother_name, student_class, school_name, address, dob, admission_date, filename))
            conn.commit()
            flash('Student added successfully!', 'success')
        except Exception as e:
            flash(f'Error occurred: {str(e)}', 'danger')
        finally:
            conn.close()
            
    return redirect(url_for('students'))

@app.route('/student/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    conn = get_db()
    student = conn.execute('SELECT * FROM students WHERE id = ?', (id,)).fetchone()
    
    if not student:
        conn.close()
        flash('Student not found.', 'danger')
        return redirect(url_for('students'))
        
    if request.method == 'POST':
        name = request.form.get('name').strip()
        mobile = request.form.get('mobile').strip()
        father_name = request.form.get('father_name').strip()
        mother_name = request.form.get('mother_name').strip()
        student_class = request.form.get('class').strip()
        school_name = request.form.get('school_name').strip()
        address = request.form.get('address').strip()
        dob = request.form.get('dob')
        admission_date = request.form.get('admission_date')
        
        if not name or not mobile:
            flash('Name and Mobile fields are mandatory.', 'danger')
            return redirect(url_for('edit_student', id=id))
            
        photo_file = request.files.get('photo')
        filename = student['photo']
        if photo_file and photo_file.filename != '':
            filename = secure_filename(f"{int(datetime.now().timestamp())}_{photo_file.filename}")
            photo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
        conn.execute('''
            UPDATE students SET name=?, mobile=?, father_name=?, mother_name=?, class=?, school_name=?, address=?, dob=?, admission_date=?, photo=?
            WHERE id=?
        ''', (name, mobile, father_name, mother_name, student_class, school_name, address, dob, admission_date, filename, id))
        conn.commit()
        conn.close()
        flash('Student profile updated successfully.', 'success')
        return redirect(url_for('student_profile', id=id))
        
    conn.close()
    return render_template('student_profile.html', student=student, edit_mode=True)

@app.route('/student/delete/<int:id>', methods=['POST'])
@login_required
def delete_student(id):
    conn = get_db()
    conn.execute('DELETE FROM students WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Student record deleted successfully.', 'warning')
    return redirect(url_for('students'))

@app.route('/student/profile/<int:id>')
@login_required
def student_profile(id):
    conn = get_db()
    student = conn.execute('SELECT * FROM students WHERE id = ?', (id,)).fetchone()
    if not student:
        conn.close()
        flash('Student not found.', 'danger')
        return redirect(url_for('students'))
        
    results = conn.execute('SELECT * FROM results WHERE student_id = ? ORDER BY id DESC', (id,)).fetchall()
    conn.close()
    return render_template('student_profile.html', student=student, results=results, edit_mode=False)

@app.route('/results', methods=['GET', 'POST'])
@login_required
def results():
    conn = get_db()
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        exam_name = request.form.get('exam_name').strip()
        total_marks = float(request.form.get('total_marks'))
        obtained_marks = float(request.form.get('obtained_marks'))
        exam_date = request.form.get('exam_date') or datetime.now().strftime('%Y-%m-%d')
        
        if obtained_marks > total_marks:
            flash('Obtained Marks cannot be greater than Total Marks.', 'danger')
            return redirect(url_for('results'))
            
        percentage, grade = calculate_grade(obtained_marks, total_marks)
        
        conn.execute('''
            INSERT INTO results (student_id, exam_name, total_marks, obtained_marks, percentage, grade, exam_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, exam_name, total_marks, obtained_marks, percentage, grade, exam_date))
        conn.commit()
        flash('Result added successfully!', 'success')
        return redirect(url_for('results'))
        
    # GET Request Logic
    search_query = request.args.get('search', '').strip()
    query = '''
        SELECT r.*, s.name as student_name, s.student_id as uid, s.class 
        FROM results r 
        JOIN students s ON r.student_id = s.id
    '''
    params = []
    if search_query:
        query += " WHERE s.name LIKE ? OR r.exam_name LIKE ? OR s.student_id LIKE ?"
        params.extend([f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'])
        
    query += " ORDER BY r.id DESC"
    result_list = conn.execute(query, params).fetchall()
    all_students = conn.execute('SELECT id, name, student_id FROM students ORDER BY name').fetchall()
    conn.close()
    
    return render_template('results.html', results=result_list, students=all_students, search_query=search_query)

@app.route('/result/delete/<int:id>', methods=['POST'])
@login_required
def delete_result(id):
    conn = get_db()
    conn.execute('DELETE FROM results WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Result entry deleted.', 'warning')
    return redirect(url_for('results'))

@app.route('/ranking')
@login_required
def ranking():
    conn = get_db()
    classes = conn.execute('SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != "" ORDER BY class').fetchall()
    
    selected_class = request.args.get('class_select', '').strip()
    ranked_students = []
    
    if selected_class:
        # Get Average Percentage for each student in the selected class
        query = '''
            SELECT s.id, s.name, s.mobile, ROUND(AVG(r.percentage), 2) as avg_percentage
            FROM students s
            JOIN results r ON s.id = r.student_id
            WHERE s.class = ?
            GROUP BY s.id
            ORDER BY avg_percentage DESC
        '''
        raw_rankings = conn.execute(query, (selected_class,)).fetchall()
        
        # Dense Ranking Algorithm Logic (Same percentage gets same rank)
        current_rank = 0
        prev_pct = None
        count = 0
        
        for row in raw_rankings:
            count += 1
            if row['avg_percentage'] != prev_pct:
                current_rank = count
                prev_pct = row['avg_percentage']
            
            # Calculate overall grade based on average percentage
            _, grade = calculate_grade(row['avg_percentage'], 100)
            
            ranked_students.append({
                'rank': current_rank,
                'name': row['name'],
                'mobile': row['mobile'],
                'percentage': row['avg_percentage'],
                'grade': grade
            })
            
    conn.close()
    return render_template('ranking.html', classes=classes, selected_class=selected_class, ranked_students=ranked_students)

@app.route('/ranking/export/pdf')
@login_required
def export_ranking_pdf():
    selected_class = request.args.get('class_select', '').strip()
    if not selected_class:
        flash('Please select a class to export PDF.', 'danger')
        return redirect(url_for('ranking'))
        
    conn = get_db()
    system_set = conn.execute('SELECT * FROM settings LIMIT 1').fetchone()
    
    query = '''
        SELECT s.name, s.mobile, ROUND(AVG(r.percentage), 2) as avg_percentage
        FROM students s
        JOIN results r ON s.id = r.student_id
        WHERE s.class = ?
        GROUP BY s.id
        ORDER BY avg_percentage DESC
    '''
    raw_rankings = conn.execute(query, (selected_class,)).fetchall()
    conn.close()
    
    # Process Ranking
    ranked_students = []
    current_rank = 0
    prev_pct = None
    count = 0
    for row in raw_rankings:
        count += 1
        if row['avg_percentage'] != prev_pct:
            current_rank = count
            prev_pct = row['avg_percentage']
        _, grade = calculate_grade(row['avg_percentage'], 100)
        ranked_students.append([current_rank, row['name'], row['mobile'], f"{row['avg_percentage']}%", grade])

    # PDF Building via ReportLab
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=24, leading=28, textColor=colors.HexColor('#0f172a'), alignment=1)
    subtitle_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=12, leading=16, textColor=colors.HexColor('#64748b'), alignment=1)
    
    # Header Elements
    story.append(Paragraph(f"<b>{system_set['tuition_name']}</b>", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Merit List / Ranking Report — Class: {selected_class}", subtitle_style))
    story.append(Paragraph(f"Generated Date: {datetime.now().strftime('%d %B, %Y')}", subtitle_style))
    story.append(Spacer(1, 20))
    
    # Table Setup
    table_data = [['Rank', 'Student Name', 'Mobile Number', 'Percentage', 'Grade']] + ranked_students
    t = Table(table_data, colWidths=[50, 180, 120, 100, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    
    # Footer Layout
    story.append(Spacer(1, 40))
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#94a3b8'), alignment=1)
    story.append(Paragraph("Generated By Tuition Management System", footer_style))
    
    doc.build(story)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f"Ranking_Class_{selected_class}.pdf", mime_type='application/pdf')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    conn = get_db()
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        if form_type == 'general':
            tuition_name = request.form.get('tuition_name').strip()
            logo_file = request.files.get('tuition_logo')
            
            if not tuition_name:
                flash('Tuition Name cannot be empty.', 'danger')
                return redirect(url_for('settings'))
                
            filename = conn.execute('SELECT tuition_logo FROM settings LIMIT 1').fetchone()['tuition_logo']
            if logo_file and logo_file.filename != '':
                filename = secure_filename(f"logo_{int(datetime.now().timestamp())}_{logo_file.filename}")
                logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
            conn.execute('UPDATE settings SET tuition_name=?, tuition_logo=? WHERE id=1', (tuition_name, filename))
            conn.commit()
            flash('General settings updated successfully.', 'success')
            
        elif form_type == 'password':
            current_password = request.form.get('current_password').strip()
            new_password = request.form.get('new_password').strip()
            confirm_password = request.form.get('confirm_password').strip()
            
            admin_data = conn.execute('SELECT * FROM admins WHERE username = ?', (session['admin_username'],)).fetchone()
            
            if not check_password_hash(admin_data['password'], current_password):
                flash('Current password is incorrect.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            elif len(new_password) < 6:
                flash('Password must be at least 6 characters long.', 'danger')
            else:
                hashed_pw = generate_password_hash(new_password)
                conn.execute('UPDATE admins SET password=? WHERE username=?', (hashed_pw, session['admin_username']))
                conn.commit()
                flash('Password changed successfully!', 'success')
                
        conn.close()
        return redirect(url_for('settings'))
        
    settings_data = conn.execute('SELECT * FROM settings LIMIT 1').fetchone()
    conn.close()
    return render_template('settings.html', settings_data=settings_data)

if __name__ == '__main__':
    app.run(debug=True)