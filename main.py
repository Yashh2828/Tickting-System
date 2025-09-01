# ====================== IMPORTS ======================
from flask import Flask, render_template, url_for, session, redirect, request, flash
from flask_pymongo import PyMongo
from datetime import datetime
from waitress import serve

# ====================== APP CONFIGURATION ======================
app = Flask(__name__)
app.secret_key = "your_secret_key"
app.config["MONGO_URI"] = "mongodb://localhost:27017/User"
mongo = PyMongo(app)

# ====================== ROUTE: HOME / INDEX ======================
@app.route("/")
def index():
    session["user_id"] = "EMP45678"  # Simulating a logged-in user for demo
    return redirect("/dashboard")

# ====================== ROUTE: DASHBOARD ======================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    user_id = session["user_id"]
    selected_status = request.args.get("status")

    # Build dynamic query based on filter
    query = {"user_id": user_id}
    if selected_status and selected_status != "all":
        query["status"] = selected_status.lower()

    # Fetch user info
    user = mongo.db["user information"].find_one({"_id": user_id})

    # Fetch and sort tickets
    all_tickets = list(mongo.db["tickets"].find(query))
    status_order = {
        "pending": 1,
        "in progress": 2,
        "resolved": 3,
        "closed": 4
    }

    # Custom sort: by status and creation date
    all_tickets.sort(key=lambda ticket: (
        status_order.get(ticket.get("status", "").lower(), 99),
        ticket.get("created_at", "")
    ))

    # Count tickets by status for dashboard summary
    pending_count = mongo.db["tickets"].count_documents({"user_id": user_id, "status": "pending"})
    in_progress_count = mongo.db["tickets"].count_documents({"user_id": user_id, "status": "in progress"})
    resolved_count = mongo.db["tickets"].count_documents({"user_id": user_id, "status": "resolved"})
    closed_count = mongo.db["tickets"].count_documents({"user_id": user_id, "status": "closed"})
    total_count = len(all_tickets)

    return render_template(
        "index.html",
        user=user,
        tickets=all_tickets,
        pending_count=pending_count,
        in_progress_count=in_progress_count,
        resolved_count=resolved_count,
        closed_count=closed_count,
        total_ticket=total_count,
        selected_status=selected_status
    )

# ====================== ROUTE: VERIFY TICKET ======================
@app.route("/verify/<ticket_id>", methods=["POST"])
def verify_ticket(ticket_id):
    if "user_id" not in session:
        return redirect("/")

    user_id = session["user_id"]

    # Only allow status change if ticket is resolved
    mongo.db["tickets"].update_one(
        {
            "_id": ticket_id,
            "user_id": user_id,
            "status": "resolved"
        },
        {
            "$set": {
                "status": "closed"
            }
        }
    )
    return redirect("/dashboard")

# ====================== ROUTE: ACCOUNT INFO PAGE ======================
@app.route("/account")
def account_info():
    if "user_id" not in session:
        return redirect("/")
    user = mongo.db["user information"].find_one({"_id": session["user_id"]})
    return render_template("account.html", user=user)

# ====================== ROUTE: ADD NEW EQUIPMENT ======================
@app.route("/equipment", methods=["GET", "POST"])
def equipment():
    if "user_id" not in session:
        flash("You must be logged in to view or add equipment.", "warning")
        return redirect(url_for("index"))

    user_id = session["user_id"]

    if request.method == "POST":
        # Handle form submission
        equipment = request.form.get("equipment")
        if equipment == "Other":
            equipment = request.form.get("custom_equipment")

        model = request.form.get("model")
        serial = request.form.get("serial")
        issue_date = request.form.get("issue_date")
        owner = request.form.get("owner")

        if not all([equipment, model, serial, issue_date, owner]):
            flash("❌ All fields are required.", "danger")
            session["show_modal"] = True 
            return redirect(url_for("equipment"))  # redirect to GET version

        # Check for unique serial number
        existing = mongo.db["equipment details"].find_one({"serial": serial})
        if existing:
            flash("❌ Serial number already exists. Please use a unique one.", "danger")
            session["show_modal"] = True 
            return redirect(url_for("equipment"))

        # Save to DB
        new_equipment = {
            "user_id": user_id,
            "equipment": equipment,
            "model": model,
            "serial": serial,
            "issue_date": issue_date,
            "owner": owner
        }
        mongo.db["equipment details"].insert_one(new_equipment)
        flash("✅ Equipment added successfully!", "success")
        session.pop("show_modal", None)
        return redirect(url_for("equipment"))  # show updated list

    # If GET request: render equipment list
    equipment_list = list(mongo.db["equipment details"].find({"user_id": user_id}))
    return render_template("equipment.html", equipment_list=equipment_list)

# ====================== ROUTE: TICKET FORM PAGE ======================
@app.route("/ticket")
def ticket():
    if "user_id" not in session:
        return redirect("/")

    user_id = session["user_id"]

    # Get raw equipment data for the logged-in user
    raw_equipments = list(mongo.db["equipment details"].find({"user_id": user_id}))

    # Format for dropdown
    user_equipments = []
    for item in raw_equipments:
        label = f"{item['equipment']} - {item['serial'][-4:]}" if len(item['serial']) >= 4 else item['equipment']
        user_equipments.append({
            "equipment": item["equipment"],
            "model": item["model"],
            "serial": item["serial"],
            "owner": item["owner"],
            "label": label
        })

    # Get user's tickets
    tickets = list(mongo.db["tickets"].find({"user_id": user_id}))

    return render_template("ticket.html", user_equipments=user_equipments, tickets=tickets)

# ====================== ROUTE: SUBMIT TICKET ======================
@app.route("/submit_ticket", methods=["POST"])
def submit_ticket():
    if "user_id" not in session:
        return redirect("/")

    user_id = session["user_id"]

    # Generate unique ticket ID
    ticket_count = mongo.db["tickets"].count_documents({"user_id": user_id})
    next_number = ticket_count + 1
    ticket_id = f"{user_id}@{next_number:04d}"

    # Collect ticket data from form
    equipment = request.form.get("equipment")
    model = request.form.get("model")
    serial = request.form.get("serial")
    owner = request.form.get("owner")
    short_desc = request.form.get("short_desc")
    long_desc = request.form.get("long_desc")

    # Compose and insert ticket
    ticket_data = {
        "_id": ticket_id,
        "user_id": user_id,
        "equipment": equipment,
        "model": model,
        "serial": serial,
        "raised_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "owner": owner,
        "short_description": short_desc,
        "detailed_description": long_desc,
        "created_at": datetime.utcnow(),
        "status": "pending"
    }

    mongo.db["tickets"].insert_one(ticket_data)
    flash("✅ Ticket submitted successfully!", "success")
    return redirect("/dashboard")

# ====================== ROUTE: LOGOUT ======================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ====================== RUN FLASK APP ======================
if __name__ == "__main__":
    #serve(app, host='0.0.0.0', port=5000)
    app.run(debug=True)
