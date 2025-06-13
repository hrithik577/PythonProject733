from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    # Create an admin user
    admin_username = 'admin'
    admin_password = 'admin123'  # Change this to a secure password
    hashed_password = generate_password_hash(admin_password)

    # Check if admin already exists
    if not User.query.filter_by(username=admin_username).first():
        admin = User(username=admin_username, password=hashed_password, role='admin')
        db.session.add(admin)
        db.session.commit()
        print(f"Admin user '{admin_username}' created successfully.")
    else:
        print(f"Admin user '{admin_username}' already exists.")