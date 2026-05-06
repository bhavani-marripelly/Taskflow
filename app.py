import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
# Railway automatically provides DATABASE_URL. We fallback to SQLite for local testing.
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    # Use absolute path for SQLite database
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'taskflow.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db_url = f"sqlite:///{db_path.replace(chr(92), '/')}"

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)

# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True)  
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20))# 'admin' or 'member'

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    deadline = db.Column(db.Date) # Added deadline as requested
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='todo') # todo, inprogress, done
    deadline = db.Column(db.Date)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    assignee = db.relationship('User', backref='tasks')

# --- DB INIT ---
with app.app_context():
    db.create_all()
    # Seed Admin User if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', name='System Admin', email='admin@taskflow.com', role='admin',
                     password=generate_password_hash('admin123'))
        db.session.add(admin)
        db.session.commit()

# --- ROUTES ---

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        if form_type == 'login':
            username = request.form.get('username')
            password = request.form.get('password')
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                session['user_id'] = user.id
                session['role'] = user.role
                session['name'] = user.name
                return redirect(url_for('dashboard'))
            flash("Invalid credentials", "error")

        elif form_type == 'signup':
            name = request.form.get('name')
            email = request.form.get('email')
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role', 'member')

            if User.query.filter((User.username == username) | (User.email == email)).first():
                flash("Username or Email already exists", "error")
            else:
                new_user = User(name=name, email=email, username=username,
                                password=generate_password_hash(password), role=role)
                db.session.add(new_user)
                db.session.commit()
                flash("Account created! Please login.", "success")
                
    return render_template('auth.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('landing'))
    
    # Logic for Dashboard Stats
    tasks = Task.query.all()
    projects = Project.query.all()

    # Filter data based on Role
    if session.get('role') != 'admin':
        # Members see tasks assigned to them
        tasks = [t for t in tasks if t.assignee_id == session['user_id']]
        # Members see all projects (read-only usually, but we'll list them)

    # Calculations
    total_projects = len(projects) if session.get('role') == 'admin' else 'N/A'
    total_tasks = len(tasks)
    
    # Pending = Not Done
    pending_tasks = len([t for t in tasks if t.status != 'done'])
    
    # Completed = Done
    completed_tasks = len([t for t in tasks if t.status == 'done'])
    
    # Overdue = Not Done AND Date < Today
    today = datetime.now().date()
    overdue_tasks = len([t for t in tasks if t.status != 'done' and t.deadline and t.deadline < today])

    return render_template('dashboard.html', 
                           total_projects=total_projects,
                           total_tasks=total_tasks,
                           completed_tasks=completed_tasks,
                           pending_tasks=pending_tasks,
                           overdue_tasks=overdue_tasks)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

@app.route('/projects', methods=['GET', 'POST'])
def projects():
    if 'user_id' not in session: return redirect(url_for('landing'))
    
    if request.method == 'POST':
        if session.get('role') != 'admin':
            flash("Only admins can create projects", "error")
        else:
            title = request.form.get('title')
            desc = request.form.get('description')
            deadline_str = request.form.get('deadline')
            
            if not title:
                flash("Project title is required", "error")
            else:
                deadline = None
                if deadline_str:
                    deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                    
                db.session.add(Project(title=title, description=desc, deadline=deadline))
                db.session.commit()
                flash("Project created successfully", "success")
                return redirect(url_for('projects'))

    project_list = Project.query.all()
    return render_template('projects.html', projects=project_list)

@app.route('/project/<int:pid>/edit', methods=['GET', 'POST'])
def edit_project(pid):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    
    project = Project.query.get_or_404(pid)
    
    if request.method == 'POST':
        title = request.form.get('title')
        desc = request.form.get('description')
        deadline_str = request.form.get('deadline')
        
        if not title:
            flash("Project title is required", "error")
        else:
            project.title = title
            project.description = desc
            if deadline_str:
                project.deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
            else:
                project.deadline = None
            db.session.commit()
            flash("Project updated successfully", "success")
            return redirect(url_for('projects'))
    
    return render_template('edit_project.html', project=project)

@app.route('/project/<int:pid>/delete', methods=['POST'])
def delete_project(pid):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    project = Project.query.get_or_404(pid)
    # Delete all tasks associated with the project
    Task.query.filter_by(project_id=pid).delete()
    db.session.delete(project)
    db.session.commit()
    flash("Project deleted successfully", "success")
    return redirect(url_for('projects'))

@app.route('/project/<int:pid>', methods=['GET', 'POST'])
def project_detail(pid):
    if 'user_id' not in session: return redirect(url_for('landing'))
    
    project = Project.query.get_or_404(pid)
    users = User.query.all()

    if request.method == 'POST':
        # Create Task
        title = request.form.get('title')
        assignee_id = request.form.get('assignee')
        deadline_str = request.form.get('deadline')
        
        deadline = None
        if deadline_str:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()

        if title:
            new_task = Task(title=title, project_id=pid, assignee_id=assignee_id, deadline=deadline)
            db.session.add(new_task)
            db.session.commit()

    # Get tasks for this project
    tasks = Task.query.filter_by(project_id=pid).all()
    # Role filter
    if session.get('role') != 'admin':
        tasks = [t for t in tasks if t.assignee_id == session['user_id']]

    return render_template('project_detail.html', project=project, tasks=tasks, users=users)

# API Endpoint: Update Task Status
@app.route('/api/task/<int:tid>/status', methods=['POST'])
def update_task_status(tid):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    task = Task.query.get_or_404(tid)
    data = request.json
    task.status = data.get('status')
    db.session.commit()
    return jsonify({'success': True})

@app.route('/task/<int:tid>/edit', methods=['GET', 'POST'])
def edit_task(tid):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    
    task = Task.query.get_or_404(tid)
    project = Project.query.get_or_404(task.project_id)
    users = User.query.all()
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        assignee_id = request.form.get('assignee')
        deadline_str = request.form.get('deadline')
        
        if not title:
            flash("Task title is required", "error")
        else:
            task.title = title
            task.description = description
            task.assignee_id = assignee_id if assignee_id else None
            if deadline_str:
                task.deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
            else:
                task.deadline = None
            db.session.commit()
            flash("Task updated successfully", "success")
            return redirect(url_for('project_detail', pid=task.project_id))
    
    return render_template('edit_task.html', task=task, project=project, users=users)

@app.route('/task/<int:tid>/delete', methods=['POST'])
def delete_task(tid):
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    task = Task.query.get_or_404(tid)
    project_id = task.project_id
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted successfully", "success")
    return redirect(url_for('project_detail', pid=project_id))

@app.route('/team')
def team():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    return render_template('team.html', users=users)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)