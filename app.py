import os
from datetime import datetime
from functools import wraps
import urllib.parse as urlparse
import psycopg2
from psycopg2.extras import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)
app.secret_key = 'super_secret_session_key_for_tuition_system'

# Render PostgreSQL Connection URL
DATABASE_URL = "postgresql://rejaul:d3Da5EK6OEhKFKsYaBMQQKYt8CoGw2gJ@dpg-d8skrt3sq97s73c3796g-a/tuition_management"

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max upload

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Database Helper Functions (PostgreSQL) ---
def get_db():
    url = urlparse.urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        dbname=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port,
        sslmode='require'
    )
    return conn

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            # Admins Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )
            ''')
            # Settings Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id SERIAL PRIMARY KEY,
                    tuition_name TEXT NOT NULL,
                    tuition_logo TEXT,
                    theme_mode TEXT DEFAULT 'dark'
                )
            ''')
            # Students Table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
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
            cur.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    id SERIAL PRIMARY KEY,
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
            cur.execute('SELECT * FROM admins WHERE username = %s', ('rejaul',))
            if not cur.fetchone():
                hashed_pw = generate_password_hash('admin123')
                cur.execute('INSERT INTO admins (username, password) VALUES (%s, %s)', ('rejaul', hashed_pw))
                
            # Seed Default Settings if not exists
            cur.execute('SELECT * FROM settings LIMIT 1')
            if not cur.fetchone():
                cur.execute('INSERT INTO settings (tuition_name, tuition_logo) VALUES (%s, %s)', ('𝔼𝕡𝕤𝕚𝕝𝕠𝕟『𝜀』', 'default_logo.png'))
            
            conn.commit()

# Initialize DB on Startup
init_db()

# --- Context Processor for Global Settings ---
@app.context_processor
def inject_settings():
    conn = get_db()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT * FROM settings LIMIT 1')
        settings_row = cur.fetchone()
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
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('SELECT * FROM admins WHERE username = %s', (username,))
            admin = cur.fetchone()
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
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT COUNT(*) FROM students')
        total_students = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(DISTINCT class) FROM students WHERE class IS NOT NULL AND class != %s', ('',))
        total_classes = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(*) FROM results')
        total_results = cur.fetchone()[0]
        
        cur.execute('SELECT * FROM students ORDER BY id DESC LIMIT 5')
        recent_students = cur.fetchall()
        
        cur.execute('''
            SELECT s.name, s.class, s.mobile, ROUND(AVG(r.percentage)::numeric, 2) as avg_pct 
            FROM students s 
            JOIN results r ON s.id = r.student_id 
            GROUP BY s.id, s.name, s.class, s.mobile 
            ORDER BY avg_pct DESC LIMIT 5
        ''')
        top_rankers = cur.fetchall()
        
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
    
    search_query = request.args.get('search', '').strip()
    class_filter = request.args.get('class_filter', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page
    
    query = "SELECT * FROM students WHERE 1=1"
    params = []
    
    if search_query:
        query += " AND (name LIKE %s OR mobile LIKE %s OR student_id LIKE %s)"
        params.extend([f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'])
        
    if class_filter:
        query += " AND class = %s"
        params.append(class_filter)
        
    with conn.cursor(cursor_factory=DictCursor) as cur:
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        cur.execute(count_query, params)
        total_records = cur.fetchone()[0]
        total_pages = (total_records + per_page - 1) // per_page
        
        query += " ORDER BY id DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])
        
        cur.execute(query, params)
        student_list = cur.fetchall()
        
        cur.execute('SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != %s ORDER BY class', ('',))
        classes = cur.fetchall()
        
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
            
        photo_file = request.files.get('photo')
        filename = None
        if photo_file and photo_file.filename != '':
            filename = secure_filename(f"{int(datetime.now().timestamp())}_{photo_file.filename}")
            photo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
        conn = get_db()
        try:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                current_year = datetime.now().strftime('%Y')
                cur.execute('SELECT id FROM students ORDER BY id DESC LIMIT 1')
                last_id_row = cur.fetchone()
                next_serial = (last_id_row['id'] + 1) if last_id_row else 1
                student_id = f"TMS-{current_year}-{next_serial:04d}"
                
                cur.execute('''
                    INSERT INTO students (student_id, name, mobile, father_name, mother_name, class, school_name, address, dob, admission_date, photo)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT * FROM students WHERE id = %s', (id,))
        student = cur.fetchone()
    
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
            
        with conn.cursor() as cur:
            cur.execute('''
                UPDATE students SET name=%s, mobile=%s, father_name=%s, mother_name=%s, class=%s, school_name=%s, address=%s, dob=%s, admission_date=%s, photo=%s
                WHERE id=%s
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
    with conn.cursor() as cur:
        cur.execute('DELETE FROM students WHERE id = %s', (id,))
    conn.commit()
    conn.close()
    flash('Student record deleted successfully.', 'warning')
    return redirect(url_for('students'))

@app.route('/student/profile/<int:id>')
@login_required
def student_profile(id):
    conn = get_db()
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT * FROM students WHERE id = %s', (id,))
        student = cur.fetchone()
        if not student:
            conn.close()
            flash('Student not found.', 'danger')
            return redirect(url_for('students'))
            
        cur.execute('SELECT * FROM results WHERE student_id = %s ORDER BY id DESC', (id,))
        results = cur.fetchall()
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
        
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO results (student_id, exam_name, total_marks, obtained_marks, percentage, grade, exam_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (student_id, exam_name, total_marks, obtained_marks, percentage, grade, exam_date))
        conn.commit()
        flash('Result added successfully!', 'success')
        return redirect(url_for('results'))
        
    search_query = request.args.get('search', '').strip()
    query = '''
        SELECT r.*, s.name as student_name, s.student_id as uid, s.class 
        FROM results r 
        JOIN students s ON r.student_id = s.id
    '''
    params = []
    if search_query:
        query += " WHERE s.name LIKE %s OR r.exam_name LIKE %s OR s.student_id LIKE %s"
        params.extend([f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'])
        
    query += " ORDER BY r.id DESC"
    
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(query, params)
        result_list = cur.fetchall()
        cur.execute('SELECT id, name, student_id FROM students ORDER BY name')
        all_students = cur.fetchall()
    conn.close()
    
    return render_template('results.html', results=result_list, students=all_students, search_query=search_query)

@app.route('/result/delete/<int:id>', methods=['POST'])
@login_required
def delete_result(id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute('DELETE FROM results WHERE id = %s', (id,))
    conn.commit()
    conn.close()
    flash('Result entry deleted.', 'warning')
    return redirect(url_for('results'))

# --- FIXED & EXAM-WISE UPGRADED RANKING ROUTE FOR POSTGRESQL ---
@app.route('/ranking')
@login_required
def ranking():
    conn = get_db()
    with conn.cursor() as cur:
        # PostgreSQL-এর জন্য সঠিক কারসর ফরমেটে ক্লাস লিস্ট নিয়ে আসা
        cur.execute("SELECT DISTINCT class FROM students WHERE class IS NOT NULL AND class != '' ORDER BY class")
        classes_raw = cur.fetchall()
        classes = [{'class': row[0]} for row in classes_raw]
        
        # ডাটাবেস থেকে সব পরীক্ষার নামের ইউনিক তালিকা নিয়ে আসা
        cur.execute("SELECT DISTINCT exam_name FROM results WHERE exam_name IS NOT NULL AND exam_name != '' ORDER BY exam_name")
        exams_raw = cur.fetchall()
        exams = [{'exam_name': row[0]} for row in exams_raw]
    
    selected_class = request.args.get('class_select', '').strip()
    selected_exam = request.args.get('exam_select', '').strip()
    ranked_students = []
    
    if selected_class and selected_exam:
        query = '''
            SELECT s.id, s.name, s.mobile, r.percentage
            FROM students s
            JOIN results r ON s.id = r.student_id
            WHERE s.class = %s AND r.exam_name = %s
            ORDER BY r.percentage DESC
        '''
        with conn.cursor() as cur:
            cur.execute(query, (selected_class, selected_exam))
            raw_rankings = cur.fetchall()
        
        current_rank = 0
        prev_pct = None
        count = 0
        
        for row in raw_rankings:
            count += 1
            exam_percentage = float(row[3]) if row[3] is not None else 0.0
            
            if exam_percentage != prev_pct:
                current_rank = count
                prev_pct = exam_percentage
            
            _, grade = calculate_grade(exam_percentage, 100)
            
            ranked_students.append({
                'rank': current_rank,
                'name': row[1],
                'mobile': row[2],
                'percentage': exam_percentage,
                'grade': grade
            })
            
    conn.close()
    return render_template('ranking.html', classes=classes, exams=exams, 
                           selected_class=selected_class, selected_exam=selected_exam, 
                           ranked_students=ranked_students)

# --- FIXED & EXAM-WISE UPGRADED PDF EXPORT FOR POSTGRESQL ---
@app.route('/ranking/export/pdf')
@login_required
def export_ranking_pdf():
    selected_class = request.args.get('class_select', '').strip()
    selected_exam = request.args.get('exam_select', '').strip()
    
    if not selected_class or not selected_exam:
        flash('Please select both class and examination to export PDF.', 'danger')
        return redirect(url_for('ranking'))
        
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute('SELECT tuition_name FROM settings LIMIT 1')
        system_set_raw = cur.fetchone()
        tuition_name = system_set_raw[0] if system_set_raw else "Tuition Management System"
        
        query = '''
            SELECT s.name, s.mobile, r.percentage
            FROM students s
            JOIN results r ON s.id = r.student_id
            WHERE s.class = %s AND r.exam_name = %s
            ORDER BY r.percentage DESC
        '''
        cur.execute(query, (selected_class, selected_exam))
        raw_rankings = cur.fetchall()
    conn.close()
    
    ranked_students = []
    current_rank = 0
    prev_pct = None
    count = 0
    for row in raw_rankings:
        count += 1
        exam_percentage = float(row[2]) if row[2] is not None else 0.0
        if exam_percentage != prev_pct:
            current_rank = count
            prev_pct = exam_percentage
        _, grade = calculate_grade(exam_percentage, 100)
        ranked_students.append([current_rank, row[0], row[1], f"{exam_percentage}%", grade])

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=24, leading=28, textColor=colors.HexColor('#0f172a'), alignment=1)
    subtitle_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=12, leading=16, textColor=colors.HexColor('#64748b'), alignment=1)
    
    story.append(Paragraph(f"<b>{tuition_name}</b>", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Merit List / Ranking Report — Class: {selected_class} | Exam: {selected_exam}", subtitle_style))
    story.append(Paragraph(f"Generated Date: {datetime.now().strftime('%d %B, %Y')}", subtitle_style))
    story.append(Spacer(1, 20))
    
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
    
    story.append(Spacer(1, 40))
    footer_style = ParagraphStyle('FooterStyle', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#94a3b8'), alignment=1)
    story.append(Paragraph("Generated By Tuition Management System", footer_style))
    
    doc.build(story)
    buffer.seek(0)
    
    # mimetype সংশোধিত (ডাউনলোড এরর আটকানোর জন্য)
    return send_file(buffer, as_attachment=True, download_name=f"Ranking_Class_{selected_class}_{selected_exam}.pdf", mimetype='application/pdf')
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
                
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute('SELECT tuition_logo FROM settings LIMIT 1')
                filename = cur.fetchone()['tuition_logo']
                if logo_file and logo_file.filename != '':
                    filename = secure_filename(f"logo_{int(datetime.now().timestamp())}_{logo_file.filename}")
                    logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
                cur.execute('UPDATE settings SET tuition_name=%s, tuition_logo=%s WHERE id=1', (tuition_name, filename))
            conn.commit()
            flash('General settings updated successfully.', 'success')
            
        elif form_type == 'password':
            current_password = request.form.get('current_password').strip()
            new_password = request.form.get('new_password').strip()
            confirm_password = request.form.get('confirm_password').strip()
            
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute('SELECT * FROM admins WHERE username = %s', (session['admin_username'],))
                admin_data = cur.fetchone()
                
                if not check_password_hash(admin_data['password'], current_password):
                    flash('Current password is incorrect.', 'danger')
                elif new_password != confirm_password:
                    flash('New passwords do not match.', 'danger')
                elif len(new_password) < 6:
                    flash('Password must be at least 6 characters long.', 'danger')
                else:
                    hashed_pw = generate_password_hash(new_password)
                    cur.execute('UPDATE admins SET password=%s WHERE username=%s', (hashed_pw, session['admin_username']))
            conn.commit()
            flash('Password changed successfully!', 'success')
                
        conn.close()
        return redirect(url_for('settings'))
        
    with conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute('SELECT * FROM settings LIMIT 1')
        settings_data = cur.fetchone()
    conn.close()
    return render_template('settings.html', settings_data=settings_data)

if __name__ == '__main__':
    app.run(debug=True)
