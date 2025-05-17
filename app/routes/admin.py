import time
from flask import Blueprint, render_template, redirect, request, flash, jsonify, url_for
from app.helpers.middleware import is_auth, is_admin, is_verified
from app.utils.table import CRUD
from app.helpers.authdata import auth_data
from app.helpers.helpers import is_email
from app.mail.support import support_mail
from app.utils.mailer import send_email
from werkzeug.security import generate_password_hash, check_password_hash
import os
import base64
from werkzeug.utils import secure_filename
import uuid
from flask import current_app

admin = Blueprint("admin", __name__, template_folder="templates")


# all admin routes
@admin.route("/")
@is_auth
@is_admin
@is_verified
def dashboard():
    try:
        customer = CRUD("users").count(role="user")
        transaction = CRUD("transactions").count()
        servers = CRUD("servers").count()
        server_data = CRUD("servers").get()
        supports = CRUD("supports").count()

        return render_template(
            "admin/dashboard.html",
            data={
                "customer": customer,
                "transaction": transaction,
                "servers": servers,
                "supports": supports,
                "server_data": server_data,
            },
        )
    except Exception as e:
        flash("server error try again!", "error")
        return render_template("admin/dashboard.html")


# all for users ==========
@admin.route("/users", methods=["POST", "GET"])
@is_auth
@is_admin
@is_verified
def users():
    data = CRUD("users").get()
    id = request.args.get("id")
    order = request.args.get("order")
    if id and order == "delete":
        delete = CRUD("users").delete(id)
        if delete:
            flash("One user deleted success", "success")
            return redirect(url_for("admin.users"))
        else:
            flash("User delete faild", "error")
            return redirect(url_for("admin.users"))
    return render_template("admin/users.html", data=data)


@admin.route("/userdata", methods=["POST"])
@is_auth
@is_verified
def userdata():
    try:
        if request.method == "POST":
            model = CRUD("users")
            id = request.json.get("id")
            if not id:
                return jsonify({"status": "error", "message": "Id must required"})

            global finaldata
            finaldata = {}
            data = model.get_by_column("id", id)
            if data:
                finaldata = data
            else:
                finaldata = model.get_by_column("email", id)

            return jsonify({"status": "success", "data": finaldata})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


@admin.route("/userupdate", methods=["POST"])
@is_auth
@is_admin
@is_verified
def userupdate():
    try:
        if request.method == "POST":
            model = CRUD("users")
            id = request.json.get("id")
            name = request.json.get("name")
            email = request.json.get("email")
            password = request.json.get("password")
            email_status = request.json.get("email_status")
            status = request.json.get("status")
            role = request.json.get("role")

            if not id:
                if not all([name, email, password, role]):
                    return jsonify({"status": "error", "message": "Id must required"})
                hashed_password = generate_password_hash(password)
                model.create(
                    name=name,
                    email=email,
                    password=hashed_password,
                    role=role,
                    email_verify=email_status,
                    status=status,
                )
                return jsonify({"status": "success", "message": "User created success"})
            else:
                if not all([id, name, email, role]):
                    return jsonify({"status": "error", "message": "Id must required"})

                update = model.update(
                    id,
                    name=name,
                    email=email,
                    role=role,
                    email_verify=email_status,
                    status=status,
                )
                if update.get("status") == "success":
                    return jsonify(
                        {"status": "success", "message": "User updated success"}
                    )
        return jsonify({"status": "error", "message": "server error try again!"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


# for full app creadites system handler from here
@admin.route("/foundadd", methods=["POST"])
@is_auth
@is_verified
def foundadd():
    try:
        if request.method == "POST":
            user_id = request.json.get("id")
            amount = request.json.get("amount")
            sender = request.json.get("sender")
            if not all([user_id, amount, sender]):
                return jsonify(
                    {"status": "error", "message": "All details are required"}
                )

            if float(amount) <= 0:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Please enter a valid amount greater than zero.",
                    }
                )

            model = CRUD("users")
            user = {}

            get_by_id = model.get_by_column("id", user_id)
            get_by_email = model.get_by_column("email", user_id)

            if get_by_id or get_by_email:
                if get_by_id:
                    user = model.get_by_column("id", user_id).get("data")
                else:
                    user = model.get_by_column("email", user_id).get("data")
            else:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Invalid user. Make sure the ID/Email is correct. You can check by clicking the verify button.",
                    }
                )

            # if user are admin
            if user and (user.get("role") == "admin" or user.get("status") == "block"):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Failed to add funds. Please try again, and ensure the provided ID or email does not belong to an admin or a blocked user.",
                    }
                )

            # if user not verifyed
            if user.get("email_verify") == "no":
                return jsonify(
                    {
                        "status": "error",
                        "message": "This user's email is not verified",
                    }
                )

            # check balance
            if sender == "share" and (
                auth_data().get("data").get("role") != "admin"
                and (
                    auth_data().get("data").get("coin") is None
                    or float(auth_data().get("data").get("coin", 0)) < float(amount)
                )
            ):
                return jsonify({"status": "error", "message": "Low balance"})

            # finally found system
            coin = user.get("coin") + float(amount)
            update = model.update(user.get("id"), coin=coin)
            if update:
                t_model = CRUD("transactions")
                found = t_model.create(
                    user_name=user.get("name"),
                    user_id=user.get("id"),
                    amount=float(amount),
                    type=sender,
                    type_details=(
                        "Add by admin"
                        if sender == "admin"
                        else "Share by " + auth_data().get("data").get("name")
                    ),
                    status="complete",
                )

                if found.get("status") == "success":
                    if sender == "share":
                        history_for_sender = t_model.create(
                            user_name=auth_data().get("data").get("name"),
                            user_id=auth_data().get("data").get("id"),
                            amount=float(amount),
                            type=sender,
                            type_details="Share with " + user.get("name"),
                            status="complete",
                        )
                        if history_for_sender:
                            updated_coin = auth_data().get("data").get("coin") - float(
                                amount
                            )
                            model.update(
                                auth_data().get("data").get("id"), coin=updated_coin
                            )
                            return jsonify(
                                {
                                    "status": "success",
                                    "message": (
                                        "Found " + "Added"
                                        if sender == "admin"
                                        else "Shared" + " successfully"
                                    ),
                                }
                            )
                    else:
                        return jsonify(
                            {
                                "status": "success",
                                "message": (
                                    "Found " + "Added"
                                    if sender == "admin"
                                    else "Shared" + " successfully"
                                ),
                            }
                        )
                else:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Failed to add found, try again",
                        }
                    )
        else:
            return jsonify({"status": "error", "message": "Invalid request method"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


# admin account =======
@admin.route("/account", methods=["GET", "POST"])
@is_auth
@is_admin
@is_verified
def account():
    try:
        user = CRUD("users")
        if request.method == "POST":
            name = request.form.get("name")
            c_password = request.form.get("c_password")
            n_password = request.form.get("n_password")
            email = request.form.get("email")
            hashed_password = generate_password_hash(n_password)

            # validation
            if not name:
                flash("Name fields are required")
                return render_template("/admin/account.html")

            # update users name
            user.update(auth_data().get("data").get("id"), name=name)
            flash("Profile updated successfully", "success")

            # if password has
            if c_password and n_password:
                # check password less cherecter
                if len(n_password) < 8:
                    flash("New Password must be at least 8 characters long", "error")
                    return render_template("/admin/account.html")

                # check hased password
                if check_password_hash(
                    auth_data().get("data").get("password"), c_password
                ):
                    user.update(
                        auth_data().get("data").get("id"), password=hashed_password
                    )
                    flash("Password updated successfully", "success")
                    return render_template("/admin/account.html")
                else:
                    flash("Current password is incorrect", "error")
                    return render_template("/admin/account.html")

            # if want to chanage email
            if email:
                # the emial already has or not
                if user.get_by_column("email", email).get("status") == "error":
                    user.update(auth_data().get("data").get("id"), email=email)
                    flash("Email Change success", "success")
                    return render_template("/admin/account.html")
                else:
                    flash(
                        "The email is already registered with another account", "error"
                    )
                    return render_template("/admin/account.html")
        else:
            return render_template("/admin/account.html")
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/account.html")


# servres all of routes ===============
@admin.route("servres", methods=["GET", "POST"])
@is_auth
@is_admin
@is_verified
def servres():
    try:
        server = CRUD("servers")
        if request.method == "POST":
            name = request.json.get("name")
            email = request.json.get("email")
            api = request.json.get("api")

            # validations
            if not all([name, email, api]):
                return jsonify(
                    {"status": "error", "message": "All Fields are required"}
                )

            if not is_email(email):
                return jsonify({"status": "error", "message": "Invalid email address"})

            # validate this server already exists or not
            if server.exists("email", email).get("data"):
                return jsonify(
                    {"status": "error", "message": "This server already added"}
                )

            # create server
            create = server.create(server_name=name, email=email, api=api)
            if create.get("status") == "success":
                return jsonify(
                    {"status": "success", "message": "New server added successfully"}
                )

            return jsonify(
                {"status": "error", "message": "Server addition failed, try again"}
            )

        # delete
        id = request.args.get("id")
        order = request.args.get("order")
        if id and order == "delete":
            server.delete(id)
            flash("One server has been deleted", "success")
            return redirect(url_for("admin.servres"))
        return render_template("/admin/servres.html", data=server.get())
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/servres.html", data={})


@admin.route("serverdata", methods=["POST"])
@is_auth
@is_admin
@is_verified
def serverdata():
    try:
        if request.method == "POST":
            model = CRUD("servers")
            id = request.json.get("id")
            if not id:
                return jsonify({"status": "error", "message": "Id must required"})
            return jsonify({"status": "success", "data": model.get_by_column("id", id)})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


@admin.route("serveredit", methods=["POST"])
@is_auth
@is_admin
@is_verified
def serveredit():
    try:
        if request.method == "POST":
            servre = CRUD("servers")
            id = request.json.get("id")
            name = request.json.get("name")
            email = request.json.get("email")
            api = request.json.get("api")

            # validations
            if not all([id, name, email, api]):
                return jsonify(
                    {"status": "error", "message": "All Fields are required"}
                )

            update = servre.update(id, server_name=name, api=api, email=email)
            if update.get("status") == "success":
                return jsonify(
                    {"status": "success", "message": "Server updated success"}
                )
        else:
            return jsonify({"status": "error", "message": "This methods not allowed!"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


@admin.route("serverstatus", methods=["POST"])
@is_auth
@is_admin
@is_verified
def serverstatus():
    try:
        if request.method == "POST":
            model = CRUD("servers")
            id = request.json.get("id")

            if not id:
                return jsonify(
                    {"status": "error", "message": "server error try again!"}
                )

            current = model.get_by_column("id", id).get("data")
            if current:
                if current.get("status") == "on":
                    model.update(id, status="off")
                else:
                    model.update(id, status="on")
                return jsonify(
                    {"status": "success", "message": "server status change success"}
                )
        return jsonify({"status": "error", "message": "server error try again!"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


# support ===============
@admin.route("/support", methods=["POST", "GET"])
@is_auth
@is_admin
@is_verified
def support():
    try:
        model = CRUD("supports")
        id = request.args.get("id")
        order = request.args.get("order")
        if id and order == "delete":
            model.delete(id)
            flash("Deleted successfull", "success")
            return redirect(url_for("admin.support"))
        return render_template("/admin/support.html", data=model.get())
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/support.html")


@admin.route("/supportreply", methods=["POST"])
@is_auth
@is_admin
@is_verified
def supportreply():
    try:
        if request.method == "POST":
            model = CRUD("supports")
            email = request.json.get("email")
            subject = request.json.get("subject")
            message = request.json.get("message")

            if not all([email, subject, message]):
                return jsonify({"status": "error", "message": "All filds are required"})

            current = model.get_by_column("email", email)
            if current:
                html = support_mail(message)
                sender = sender = send_email(
                    subject,
                    [email],
                    "",
                    html,
                )
                if sender:
                    model.update(
                        current.get("data").get("id"),
                        reply=current.get("data").get("reply") + 1,
                    )
                    return jsonify(
                        {
                            "status": "success",
                            "message": "Reply sent successfully",
                        }
                    )
                else:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Failed to send email",
                        }
                    )
    except Exception as e:
        return jsonify({"status": "error", "message": "Server error try again"})


# transaction ===============
@admin.route("/transaction", methods=["POST", "GET"])
@is_auth
@is_admin
@is_verified
def transaction():
    try:
        model = CRUD("transactions")
        if request.method == "POST":
            return
        else:
            id = request.args.get("id")
            order = request.args.get("order")
            if id and order == "delete":
                model.delete(id)
                flash("Deleted successfull", "success")
                return redirect(url_for("admin.transaction"))
            return render_template("/admin/transaction.html", data=model.get())
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/transaction.html", data={})


# verifications ==========
@admin.route("/verifications", methods=["GET"])
@is_auth
@is_admin
@is_verified
def verifications():
    try:
        model = CRUD("verifications")
        id = request.args.get("id")
        order = request.args.get("order")
        if id and order == "delete":
            model.delete(id)
            flash("Deleted successfull", "success")
            return redirect(url_for("admin.verifications"))
        return render_template("/admin/verifications.html", data=model.get())
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/verifications.html", data={})


# services ===============
@admin.route("/services", methods=["GET"])
@is_auth
@is_admin
@is_verified
def services():
    try:
        return render_template("/admin/services.html")
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/services.html")


@admin.route("/servicesdata", methods=["POST"])
@is_auth
@is_admin
@is_verified
def servicesdata():
    try:
        model = CRUD("services")
        return jsonify({"status": "success", "data": model.get()})
    except Exception as e:
        return jsonify({"status": "error", "message": "Server error"})


@admin.route("servicestatus", methods=["POST"])
@is_auth
@is_admin
@is_verified
def servicestatus():
    try:
        if request.method == "POST":
            model = CRUD("services")
            id = request.json.get("id")

            if not id:
                return jsonify(
                    {"status": "error", "message": "Server error try again!"}
                )

            current = model.get_by_column("id", id).get("data")
            if current:
                if current.get("status") == "on":
                    model.update(id, status="off")
                else:
                    model.update(id, status="on")
                return jsonify(
                    {
                        "status": "success",
                        "message": "Service status change success",
                        "data": model.get_by_column("id", id).get("data").get("status"),
                    }
                )
        return jsonify({"status": "error", "message": "server error try again!"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


@admin.route("servicesdatasingle", methods=["POST"])
@is_auth
@is_admin
@is_verified
def servicesdatasingle():
    try:
        if request.method == "POST":
            model = CRUD("services")
            id = request.json.get("id")

            if not id:
                return jsonify(
                    {"status": "error", "message": "Server error try again!"}
                )

            current = model.get_by_column("id", id).get("data")
            if current:
                return jsonify(
                    {
                        "status": "success",
                        "data": current,
                    }
                )
        return jsonify({"status": "error", "message": "server error try again!"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


@admin.route("/serviceupdate", methods=["POST"])
@is_auth
@is_admin
@is_verified
def serviceupdate():
    try:
        model = CRUD("services")
        id = request.json.get("id")
        c_name = request.json.get("c_name")
        discount = request.json.get("discount")
        logo_data = request.json.get("logo")

        model_data = model.get_by_column("id", id).get("data")

        if not id:
            return jsonify({"status": "error", "message": "Server error try again!"})

        if not c_name:
            return jsonify({"status": "error", "message": "Custome name is required"})

        # Handle logo upload from base64
        logo_filename = handle_logo_upload(base64_logo_data=logo_data, identifier=id)
        # Update service data
        update_data = {"custome_name": c_name}
        if logo_filename:
            update_data["image"] = (
                f"{current_app.config.get('APP_URL')}/static/media/uploads/{logo_filename}"
            )
        if discount:
            update_data["discount"] = discount
            update_data["selling_price"] = round(
                float(model_data.get("price")) * (1 - float(discount) / 100), 2
            )
        else:
            update_data["selling_price"] = float(model_data.get("price"))

        update = model.update(id, **update_data)
        if update.get("status") == "success":
            return jsonify(
                {
                    "status": "success",
                    "message": "Service updated successfully",
                    "old": model.get_by_column("id", id),
                }
            )
        else:
            return jsonify({"status": "error", "message": "Failed to update service"})
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


# handle logo
def handle_logo_upload(
    base64_logo_data, identifier, upload_folder="app/static/media/uploads"
):
    if not base64_logo_data:
        return None

    # Prepare upload directory
    os.makedirs(upload_folder, exist_ok=True)
    if not os.access(upload_folder, os.W_OK):
        raise PermissionError(f"Cannot write to directory: {upload_folder}")

    # Handle data URL if present
    if base64_logo_data.startswith("data:"):
        parts = base64_logo_data.split(",")
        if len(parts) != 2:
            raise ValueError("Invalid data URL format")
        metadata, base64_logo_data = parts
        mime_type = metadata.split(";")[0].split(":")[1]
        extension = mime_type.split("/")[-1].lower()
    else:
        extension = "png"  # default extension

    # Generate secure filename pattern
    filename_pattern = f"logo_{secure_filename(str(identifier))}_"

    # Clean up any existing files with this pattern
    for existing_file in os.listdir(upload_folder):
        if existing_file.startswith(filename_pattern):
            try:
                os.remove(os.path.join(upload_folder, existing_file))
            except OSError as e:
                print(f"Warning: Could not delete old logo file {existing_file}: {e}")

    # Generate new filename
    filename = f"{filename_pattern}{uuid.uuid4().hex[:8]}.{extension}"
    filepath = os.path.join(upload_folder, filename)

    try:
        # Decode and save
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(base64_logo_data))

        return filename

    except base64.binascii.Error as e:
        raise ValueError("Invalid base64 data") from e
    except Exception as e:
        # Clean up if file was partially written
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass
        raise


# revews ============
@admin.route("/reviews", methods=["GET"])
@is_auth
@is_admin
@is_verified
def reviews():
    try:
        model = CRUD("reviews")
        id = request.args.get("id")
        order = request.args.get("order")
        if id and order == "delete":
            model.delete(id)
            flash("Deleted successfull", "success")
            return redirect(url_for("admin.reviews"))
        return render_template("/admin/reviews.html", data=model.get())
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/reviews.html", data={})


@admin.route("/reviewfeture", methods=["POST"])
@is_auth
@is_admin
@is_verified
def reviewfeture():
    try:
        model = CRUD("reviews")
        id = request.json.get("id")

        if not id:
            return jsonify({"status": "error", "message": "Server error try again!"})

        if (
            model.get_by_column("id", id).get("data").get("feture") == "off"
            and (model.count(feture="on").get("data") or 0) >= 6
        ):
            return jsonify(
                {
                    "status": "error",
                    "message": "You can only have up to 6 featured reviews",
                }
            )

        current = model.get_by_column("id", id).get("data")
        if current:
            if current.get("feture") == "on":
                model.update(id, feture="off")
            else:
                model.update(id, feture="on")
            return jsonify(
                {
                    "status": "success",
                    "message": "Review feture change success",
                    "data": model.get_by_column("id", id).get("data").get("feture"),
                }
            )
    except Exception as e:
        return jsonify({"status": "error", "message": "server error try again!"})


# settings ===============
@admin.route("/settings", methods=["GET"])
@is_auth
@is_admin
@is_verified
def settings():
    try:
        setting_discount = CRUD("discount").first()
        setting_seo = CRUD("seo").first()
        smtp = CRUD("smtp").first()
        logs = CRUD("logs").get()
        stripe = CRUD("stripe").first()
        paypal = CRUD("paypal").first()
        crypto = CRUD("crypto").first()
        amount_step = CRUD("amount_step").order_by_small_value("amount")
        services = CRUD("services").get()
        deposit = CRUD("credit_status").first()
        users = CRUD("users").get()
        return render_template(
            "/admin/settings.html",
            data={
                "setting_discount": setting_discount if setting_discount else {},
                "setting_seo": setting_seo if setting_seo else {},
                "smtp": smtp if smtp else {},
                "logs": logs if logs else {},
                "stripe": stripe if stripe else {},
                "paypal": paypal if paypal else {},
                "crypto": crypto if crypto else {},
                "amount_step": amount_step if amount_step else {},
                "services": services if services else [],
                "deposit": deposit if deposit else {},
                "users": users if users else [],
            },
        )
    except Exception as e:
        flash("An error occurred. Please try again", "error")
        return render_template("/admin/settings.html")


@admin.route("/setting/discount", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_discount():
    try:
        discount_code = request.form.get("discount_code")
        if not discount_code:
            flash("Discount code is required", "error")
            return redirect(url_for("admin.settings", tab="discount"))
        model = CRUD("discount")
        first_row = model.first()
        if first_row:
            model.update(first_row.get("data").get("id"), value=discount_code)
            flash("Discount code updated successfully", "success")
            return redirect(url_for("admin.settings", tab="discount"))
        else:
            model.create(value=discount_code)
            flash("Discount code updated successfully", "success")
            return redirect(url_for("admin.settings", tab="discount"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="discount"))


@admin.route("/setting/seo", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_seo():
    try:
        website_title = request.form.get("web_title")
        web_url = request.form.get("web_url")
        description = request.form.get("description")
        keywords = request.form.get("keywords")
        og_title = request.form.get("og_title")
        og_description = request.form.get("og_description")
        og_image = request.files.get("og_image")
        if not all([website_title, description, keywords, og_title, og_description]):
            flash("All fields are required", "error")
            return redirect(url_for("admin.settings", tab="seo"))

        model = CRUD("seo")
        og_image_filename = None
        first_row = model.first()

        # update row
        if first_row:
            # upload image
            if og_image and first_row.get("data"):
                upload_folder = "app/static/media/uploads"
                os.makedirs(upload_folder, exist_ok=True)
                # Delete old image if exists
                old_image = first_row.get("data").get("og_image", None)
                if old_image:
                    old_filename = old_image.split("/")[-1]
                    old_filepath = os.path.join(upload_folder, old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)
                filename = f"og_image_{time.time()}.{og_image.filename.split('.')[-1]}"
                filepath = os.path.join(upload_folder, filename)
                og_image.save(filepath)
                og_image_filename = f"{current_app.config.get('APP_URL')}/static/media/uploads/{filename}"
            # update
            model.update(
                first_row.get("data").get("id"),
                website_title=website_title,
                web_url=web_url,
                description=description,
                keywords=keywords,
                og_title=og_title,
                og_description=og_description,
                og_image=(
                    og_image_filename
                    if og_image_filename
                    else first_row.get("data").get("og_image")
                ),
            )
            flash("SEO settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="seo"))
        else:
            model.create(
                website_title=website_title,
                web_url=web_url,
                description=description,
                keywords=keywords,
                og_title=og_title,
                og_description=og_description,
                og_image=og_image_filename if og_image_filename else None,
            )
            flash("SEO settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="seo"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="seo"))


@admin.route("/setting/smtp", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_smtp():
    try:
        host = request.form.get("host")
        port = request.form.get("port")
        username = request.form.get("username")
        password = request.form.get("password")
        company_name = request.form.get("company_name")
        if not all([host, port, username, password, company_name]):
            flash("All fields are required", "error")
            return redirect(url_for("admin.settings", tab="smtp"))

        model = CRUD("smtp")
        first_row = model.first()
        if first_row:
            model.update(
                first_row.get("data").get("id"),
                host=host,
                port=port,
                username=username,
                password=password,
                company_name=company_name,
            )
            flash("SMTP settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="smtp"))
        else:
            model.create(
                host=host,
                port=port,
                username=username,
                password=password,
                company_name=company_name,
            )
            flash("SMTP settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="smtp"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="smtp"))


@admin.route("/setting/logs", methods=["GET"])
@is_auth
@is_admin
@is_verified
def setting_logs():
    try:
        model = CRUD("logs")
        model.delete_all()
        flash("Logs cleared successfully", "success")
        return redirect(url_for("admin.settings", tab="logs"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="logs"))


@admin.route("/setting/status", methods=["GET"])
@is_auth
@is_admin
@is_verified
def setting_status():
    try:
        if request.args.get("status") == "on":
            status = "on"
        else:
            status = "off"

        if request.args.get("type") == "stripe":
            model = CRUD("stripe")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="payment"))

        if request.args.get("type") == "paypal":
            model = CRUD("paypal")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="payment"))

        if request.args.get("type") == "crypto":
            model = CRUD("crypto")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="payment"))

        if request.args.get("type") == "logo":
            model = CRUD("identity")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), logo_status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="identity"))

        if request.args.get("type") == "favicon":
            model = CRUD("identity")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), favicon_status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="identity"))

        if request.args.get("type") == "discount" and request.args.get("id"):
            model = CRUD("services")
            first_row = model.get_by_column("id", request.args.get("id"))
            if first_row:
                model.update(first_row.get("data").get("id"), discount_status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="discount"))

        if request.args.get("type") == "deposit":
            model = CRUD("credit_status")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), deposit=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="user_payment"))
            else:
                model.create(deposit=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="user_payment"))

        if request.args.get("type") == "coin_share":
            model = CRUD("credit_status")
            first_row = model.first()
            if first_row:
                model.update(first_row.get("data").get("id"), coin_share=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="user_payment"))
            else:
                model.create(deposit=status, coin_share=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="user_payment"))
            
        if request.args.get("type") == "user_deposit_status":
            model = CRUD("users")
            first_row = model.get_by_column("id", request.args.get("id"))
            if first_row:
                model.update(first_row.get("data").get("id"), deposit_status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="user_payment"))
            
        if request.args.get("type") == "user_share_coin_status":
            model = CRUD("users")
            first_row = model.get_by_column("id", request.args.get("id"))
            if first_row:
                model.update(first_row.get("data").get("id"), share_coin_status=status)
                flash("Payment settings updated successfully", "success")
                return redirect(url_for("admin.settings", tab="user_payment"))

    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="payment"))


@admin.route("/setting/stripe", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_stripe():
    try:
        btn_label = request.form.get("stripe_btn_label")
        secret_key = request.form.get("stripe_secret_key")
        publishable_key = request.form.get("stripe_public_key")
        if not all([secret_key, publishable_key]):
            flash("All fields are required", "error")
            return redirect(url_for("admin.settings", tab="payment"))
        model = CRUD("stripe")
        first_row = model.first()
        if first_row:
            model.update(
                first_row.get("data").get("id"),
                btn_label=btn_label,
                secret_key=secret_key,
                publishable_key=publishable_key,
            )
            flash("Payment settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="payment"))
        else:
            model.create(
                btn_label=btn_label,
                secret_key=secret_key,
                publishable_key=publishable_key,
            )
            flash("Payment settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="payment"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="payment"))


@admin.route("/setting/paypal", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_paypal():
    try:
        btn_label = request.form.get("paypal_btn_label")
        secret_key = request.form.get("paypal_secret_key")
        client_id = request.form.get("paypal_client_id")
        if not all([secret_key, client_id]):
            flash("All fields are required", "error")
            return redirect(url_for("admin.settings", tab="payment"))
        model = CRUD("paypal")
        first_row = model.first()
        if first_row:
            model.update(
                first_row.get("data").get("id"),
                btn_label=btn_label,
                secret_key=secret_key,
                client_id=client_id,
            )
            flash("Payment settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="payment"))
        else:
            model.create(
                btn_label=btn_label,
                secret_key=secret_key,
                client_id=client_id,
            )
            flash("Payment settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="payment"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="payment"))


@admin.route("/setting/crypto", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_crypto():
    try:
        api_key = request.form.get("crypto_api_key")
        if not api_key:
            flash("All fields are required", "error")
            return redirect(url_for("admin.settings", tab="payment"))
        model = CRUD("crypto")
        first_row = model.first()
        if first_row:
            model.update(first_row.get("data").get("id"), api_key=api_key)
            flash("Payment settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="payment"))
        else:
            model.create(api_key=api_key)
            flash("Payment settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="payment"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="payment"))

@admin.route("/setting/amount_step", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_amount_step():
    try:
        amount = request.form.get("amount")
        if not amount:
            flash("Amount is required", "error")
            return redirect(url_for("admin.settings", tab="payment"))
        model = CRUD("amount_step")
        model.create(amount=amount)
        flash("Amount step updated successfully", "success")
        return redirect(url_for("admin.settings", tab="payment"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="payment"))


@admin.route("/setting/amount_step/delete", methods=["GET"])
@is_auth
@is_admin
@is_verified
def setting_amount_step_delete():
    try:
        id = request.args.get("id")
        model = CRUD("amount_step")
        model.delete(id)
        flash("Amount step deleted successfully", "success")
        return redirect(url_for("admin.settings", tab="payment"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="payment"))


@admin.route("/setting/identity", methods=["POST"])
@is_auth
@is_admin
@is_verified
def setting_identity():
    try:
        logo = request.files.get("logo")
        favicon = request.files.get("favicon")
        model = CRUD("identity")
        first_row = model.first()

        logo_filename = None
        favicon_filename = None
        if first_row:
            # for logo
            if logo:
                upload_folder = "app/static/media/uploads"
                os.makedirs(upload_folder, exist_ok=True)

                # Delete old image if exists
                old_image = first_row.get("data").get("logo", None)
                if old_image:
                    old_filename = old_image.split("/")[-1]
                    old_filepath = os.path.join(upload_folder, old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)

                filename = f"logo_{time.time()}.{logo.filename.split('.')[-1]}"
                filepath = os.path.join(upload_folder, filename)
                logo.save(filepath)
                logo_filename = filename

            # for favicon
            if favicon:
                upload_folder = "app/static/media/uploads"
                os.makedirs(upload_folder, exist_ok=True)

                # Delete old image if exists
                old_image = first_row.get("data").get("favicon", None)
                if old_image:
                    old_filename = old_image.split("/")[-1]
                    old_filepath = os.path.join(upload_folder, old_filename)
                    if os.path.exists(old_filepath):
                        os.remove(old_filepath)

                filename = f"favicon_{time.time()}.{favicon.filename.split('.')[-1]}"
                filepath = os.path.join(upload_folder, filename)
                favicon.save(filepath)
                favicon_filename = filename

            model.update(
                first_row.get("data").get("id"),
                logo=(
                    logo_filename
                    if logo_filename
                    else first_row.get("data").get("logo", None)
                ),
                favicon=(
                    favicon_filename
                    if favicon_filename
                    else first_row.get("data").get("favicon", None)
                ),
            )
            flash("Identity settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="identity"))
        else:
            model.create(
                logo=logo_filename if logo_filename else None,
                favicon=favicon_filename if favicon_filename else None,
            )
            flash("Identity settings updated successfully", "success")
            return redirect(url_for("admin.settings", tab="identity"))
    except Exception as e:
        flash("server error try again!", "error")
        return redirect(url_for("admin.settings", tab="identity"))
