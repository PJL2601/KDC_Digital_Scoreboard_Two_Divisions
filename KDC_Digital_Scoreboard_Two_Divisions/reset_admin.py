"""Reset an administrator password.

    python reset_admin.py boys      (resets in the Boys database)
    python reset_admin.py girls     (resets in the Girls database)
    python reset_admin.py           (uses KDC_DIVISION / the original database)
"""
import os
import sys

if len(sys.argv) > 1 and sys.argv[1].lower() in ("boys", "girls"):
    os.environ["KDC_DIVISION"] = sys.argv[1].lower()

from getpass import getpass
from app import app, db, Admin, DIVISION
from werkzeug.security import generate_password_hash


print(f"Database: {DIVISION or 'original single database'}")

with app.app_context():
    admins = Admin.query.order_by(Admin.id).all()

    if not admins:
        print("No administrator accounts found.")
    else:
        print("\nExisting administrator accounts:")

        for admin in admins:
            print(f"ID: {admin.id} | Username: {admin.username}")

        username = input("\nEnter your administrator username: ").strip()
        admin = Admin.query.filter_by(username=username).first()

        if not admin:
            print("Username not found. No changes made.")
        else:
            password = getpass("Enter your new password: ")

            if len(password) < 12:
                print("Password must contain at least 12 characters.")
            else:
                confirm = getpass("Confirm your new password: ")

                if password != confirm:
                    print("Passwords do not match. No changes made.")
                else:
                    admin.password_hash = generate_password_hash(password)
                    db.session.commit()
                    print(f"Password reset successfully for {admin.username}.")