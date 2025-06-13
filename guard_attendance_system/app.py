from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import io
import base64
from PIL import Image
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import csv
from io import StringIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///guard_attendance.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB limit
db = SQLAlchemy(app)


# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin or guard
    unit_id = db.Column(db.Integer, db.ForeignKey('unit.id'), nullable=True)


class Unit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guard_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time_in = db.Column(db.DateTime, nullable=True)
    time_out = db.Column(db.DateTime, nullable=True)
    photo_in = db.Column(db.String(200), nullable=True)
    photo_out = db.Column(db.String(200), nullable=True)


class HourlyCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guard_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    photo = db.Column(db.String(200), nullable=False)


# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


# Helper Functions
def generate_salary_report(unit_id, month, year):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(100, 750, f"Salary Report for {month}/{year}")

    guards = User.query.filter_by(role='guard', unit_id=unit_id).all()
    y = 700
    total_salary = 0

    for guard in guards:
        attendances = Attendance.query.filter_by(guard_id=guard.id).filter(
            db.extract('month', Attendance.date) == month,
            db.extract('year', Attendance.date) == year
        ).all()
        days_present = sum(1 for att in attendances if att.time_in and att.time_out)
        salary = days_present * 1000  # 1k per day
        c.drawString(100, y, f"Guard: {guard.username}, Days: {days_present}, Salary: {salary}")
        total_salary += salary
        y -= 20

    c.drawString(100, y - 20, f"Total Salary: {total_salary}")
    c.save()
    buffer.seek(0)
    return buffer


def generate_attendance_csv(unit_id, month, year):
    guards = User.query.filter_by(role='guard', unit_id=unit_id).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Guard Username', 'Date', 'Time In', 'Time Out'])

    for guard in guards:
        attendances = Attendance.query.filter_by(guard_id=guard.id).filter(
            db.extract('month', Attendance.date) == month,
            db.extract('year', Attendance.date) == year
        ).all()
        for att in attendances:
            time_in = att.time_in.strftime('%Y-%m-%d %H:%M:%S') if att.time_in else 'N/A'
            time_out = att.time_out.strftime('%Y-%m-%d %H:%M:%S') if att.time_out else 'N/A'
            writer.writerow([guard.username, att.date, time_in, time_out])

    output.seek(0)
    return output


def save_photo(photo_data, filename):
    photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img_data = base64.b64decode(photo_data.split(',')[1])
    with open(photo_path, 'wb') as f:
        f.write(img_data)
    return filename


def check_missed_hourly_photos():
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    guards = User.query.filter_by(role='guard').all()
    missed = []

    for guard in guards:
        recent_check = HourlyCheck.query.filter_by(guard_id=guard.id).filter(
            HourlyCheck.timestamp >= one_hour_ago
        ).first()
        if not recent_check:
            missed.append(guard.username)
    return missed


# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('guard_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    units = Unit.query.all()
    missed_photos = check_missed_hourly_photos()
    return render_template('admin_dashboard.html', units=units, missed_photos=missed_photos)


@app.route('/admin/add_unit', methods=['POST'])
def add_unit():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    name = request.form['name']
    if Unit.query.filter_by(name=name).first():
        flash('Unit name already exists')
        return redirect(url_for('admin_dashboard'))
    unit = Unit(name=name)
    db.session.add(unit)
    db.session.commit()
    flash('Unit added successfully')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_unit/<int:unit_id>')
def delete_unit(unit_id):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    unit = Unit.query.get(unit_id)
    db.session.delete(unit)
    db.session.commit()
    flash('Unit deleted successfully')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/add_guard', methods=['POST'])
def add_guard():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    username = request.form['username']
    password = request.form['password']
    unit_id = request.form['unit_id']
    if User.query.filter_by(username=username).first():
        flash('Username already exists')
        return redirect(url_for('admin_dashboard'))
    user = User(username=username, password=generate_password_hash(password), role='guard', unit_id=unit_id)
    db.session.add(user)
    db.session.commit()
    flash('Guard added successfully')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/edit_guard/<int:guard_id>', methods=['GET', 'POST'])
def edit_guard(guard_id):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    guard = User.query.get(guard_id)
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        unit_id = request.form['unit_id']
        if User.query.filter_by(username=username).first() and username != guard.username:
            flash('Username already exists')
            return redirect(url_for('edit_guard', guard_id=guard_id))
        guard.username = username
        if password:
            guard.password = generate_password_hash(password)
        guard.unit_id = unit_id
        db.session.commit()
        flash('Guard updated successfully')
        return redirect(url_for('view_unit', unit_id=guard.unit_id))
    units = Unit.query.all()
    return render_template('edit_guard.html', guard=guard, units=units)


@app.route('/admin/delete_guard/<int:guard_id>')
def delete_guard(guard_id):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    guard = User.query.get(guard_id)
    unit_id = guard.unit_id
    db.session.delete(guard)
    db.session.commit()
    flash('Guard deleted successfully')
    return redirect(url_for('view_unit', unit_id=unit_id))


@app.route('/admin/unit/<int:unit_id>')
def view_unit(unit_id):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    unit = Unit.query.get(unit_id)
    guards = User.query.filter_by(unit_id=unit_id, role='guard').all()
    return render_template('unit_details.html', unit=unit, guards=guards)


@app.route('/admin/view_photos/<int:guard_id>')
def view_photos(guard_id):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    guard = User.query.get(guard_id)
    hourly_checks = HourlyCheck.query.filter_by(guard_id=guard_id).order_by(HourlyCheck.timestamp.desc()).all()
    attendances = Attendance.query.filter_by(guard_id=guard_id).order_by(Attendance.date.desc()).limit(30).all()
    return render_template('view_photos.html', guard=guard, hourly_checks=hourly_checks, attendances=attendances)


@app.route('/admin/generate_report/<int:unit_id>/<int:month>/<int:year>')
def generate_report(unit_id, month, year):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    buffer = generate_salary_report(unit_id, month, year)
    return send_file(buffer, download_name=f"salary_report_{month}_{year}.pdf", as_attachment=True)


@app.route('/admin/export_attendance/<int:unit_id>/<int:month>/<int:year>')
def export_attendance(unit_id, month, year):
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'admin':
        return redirect(url_for('login'))
    output = generate_attendance_csv(unit_id, month, year)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        download_name=f"attendance_{month}_{year}.csv",
        as_attachment=True,
        mimetype='text/csv'
    )


@app.route('/guard/dashboard')
def guard_dashboard():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'guard':
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    today = datetime.now().date()
    attendance = Attendance.query.filter_by(guard_id=user.id, date=today).first()
    past_attendances = Attendance.query.filter_by(guard_id=user.id).filter(
        Attendance.date >= (today - timedelta(days=30))
    ).order_by(Attendance.date.desc()).all()
    return render_template('guard_dashboard.html', user=user, attendance=attendance, past_attendances=past_attendances)


@app.route('/guard/mark_attendance', methods=['POST'])
def mark_attendance():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'guard':
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    today = datetime.now().date()
    attendance = Attendance.query.filter_by(guard_id=user.id, date=today).first()

    photo_data = request.form['photo']

    if not attendance:
        attendance = Attendance(guard_id=user.id, date=today)
        db.session.add(attendance)

    if 'time_in' in request.form:
        attendance.time_in = datetime.now()
        attendance.photo_in = save_photo(photo_data, f"{user.id}_in_{today}.png")
    else:
        attendance.time_out = datetime.now()
        attendance.photo_out = save_photo(photo_data, f"{user.id}_out_{today}.png")

    db.session.commit()
    flash('Attendance marked successfully')
    return redirect(url_for('guard_dashboard'))


@app.route('/guard/hourly_check', methods=['POST'])
def hourly_check():
    if 'user_id' not in session or User.query.get(session['user_id']).role != 'guard':
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    photo_data = request.form['photo']

    check = HourlyCheck(
        guard_id=user.id,
        timestamp=datetime.now(),
        photo=save_photo(photo_data, f"{user.id}_hourly_{datetime.now().strftime('%Y%m%d%H%M%S')}.png")
    )
    db.session.add(check)
    db.session.commit()
    flash('Hourly photo submitted successfully')
    return redirect(url_for('guard_dashboard'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)