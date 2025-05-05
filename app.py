from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import (
    UserMixin,
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SECRET_KEY"] = "your-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///plant_reminder.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif"}

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    plants = db.relationship("Plant", backref="owner", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Plant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    species = db.Column(db.String(100), nullable=True)
    watering_interval = db.Column(db.Integer, nullable=False)
    last_watered = db.Column(db.DateTime, default=None)
    next_watering = db.Column(db.DateTime)
    image_filename = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def update_next_watering(self):
        if self.last_watered is None:
            self.next_watering = datetime.utcnow()
        else:
            self.next_watering = self.last_watered + timedelta(
                days=self.watering_interval
            )

    def needs_water(self):
        if self.last_watered is None:
            return True
        return datetime.utcnow() >= self.next_watering


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already taken. Please choose another one.")
            return redirect(url_for("register"))

        user = User(username=username)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful! Please login.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        remember = "remember" in request.form

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash("Invalid username or password")
            return redirect(url_for("login"))

        login_user(user, remember=remember)
        flash("Login successful!")

        next_page = request.args.get("next")
        if not next_page or next_page.startswith("//") or ":" in next_page:
            next_page = url_for("index")

        return redirect(next_page)

    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    plants = Plant.query.filter_by(user_id=current_user.id).all()
    return render_template("index.html", plants=plants)


@app.route("/add_plant", methods=["GET", "POST"])
@login_required
def add_plant():
    if request.method == "POST":
        name = request.form["name"]
        species = request.form["species"]
        watering_interval = int(request.form["watering_interval"])

        image_filename = None
        if "plant_image" in request.files:
            file = request.files["plant_image"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))

        new_plant = Plant(
            name=name,
            species=species,
            watering_interval=watering_interval,
            last_watered=None,
            image_filename=image_filename,
            user_id=current_user.id,
        )

        new_plant.update_next_watering()

        db.session.add(new_plant)
        db.session.commit()

        flash(f'Plant "{name}" added successfully. Don\'t forget to water it!')
        return redirect(url_for("index"))

    return render_template("add_plant.html")


@app.route("/edit_plant/<int:plant_id>", methods=["GET", "POST"])
@login_required
def edit_plant(plant_id):
    plant = Plant.query.get_or_404(plant_id)

    if plant.user_id != current_user.id:
        flash("Access denied. This plant does not belong to you.")
        return redirect(url_for("index"))

    if request.method == "POST":
        plant.name = request.form["name"]
        plant.species = request.form["species"]
        plant.watering_interval = int(request.form["watering_interval"])

        if "plant_image" in request.files:
            file = request.files["plant_image"]
            if file and file.filename and allowed_file(file.filename):
                if plant.image_filename:
                    old_image_path = os.path.join(
                        app.config["UPLOAD_FOLDER"], plant.image_filename
                    )
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)

                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                plant.image_filename = f"{timestamp}_{filename}"
                file.save(
                    os.path.join(app.config["UPLOAD_FOLDER"], plant.image_filename)
                )

        plant.update_next_watering()
        db.session.commit()

        flash("Plant updated successfully")
        return redirect(url_for("index"))

    return render_template("edit_plant.html", plant=plant)


@app.route("/water_plant/<int:plant_id>")
@login_required
def water_plant(plant_id):
    plant = Plant.query.get_or_404(plant_id)

    if plant.user_id != current_user.id:
        flash("Access denied. This plant does not belong to you.")
        return redirect(url_for("index"))

    plant.last_watered = datetime.utcnow()
    plant.update_next_watering()
    db.session.commit()
    flash(f"{plant.name} has been watered!")
    return redirect(url_for("index"))


@app.route("/delete_plant/<int:plant_id>")
@login_required
def delete_plant(plant_id):
    plant = Plant.query.get_or_404(plant_id)

    if plant.user_id != current_user.id:
        flash("Access denied. This plant does not belong to you.")
        return redirect(url_for("index"))

    if plant.image_filename:
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], plant.image_filename)
        if os.path.exists(image_path):
            os.remove(image_path)

    db.session.delete(plant)
    db.session.commit()
    flash("Plant deleted successfully")
    return redirect(url_for("index"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
