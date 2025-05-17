from flask import Flask, g, render_template
from flask_mysqldb import MySQL
from app.routes.admin import admin
from app.routes.user import user
from app.routes.pay import pay
from app.routes.api import api
from app.routes.landing import landing
from app.helpers.authdata import auth_data
from app.helpers.settings import (
    get_seo_settings,
    get_smtp_settings,
    get_stripe_data,
    get_paypal_data,
    get_crypto_data,
    get_amount_step,
    get_identity_settings,
    get_user_payment_settings,
)
from app.helpers.helpers import get_media
from config import Config
from app.utils.mailer import send_email
from flask_apscheduler import APScheduler

db = MySQL()
scheduler = APScheduler()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize MySQL
    db.init_app(app)

    # Initialize scheduler
    scheduler.init_app(app)
    scheduler.start()

    # Set the email function globally
    @app.before_request
    def set_mailer():
        g.send_email = send_email

    # Global database connection
    @app.before_request
    def set_db():
        g.db = db

    # App-wide context processors
    @app.context_processor
    def inject_globals():
        return {
            "auth_data": auth_data(),
            "get_media": get_media,
            "get_seo_settings": get_seo_settings,
            "get_smtp_settings": get_smtp_settings,
            "get_stripe_data": get_stripe_data,
            "get_paypal_data": get_paypal_data,
            "get_crypto_data": get_crypto_data,
            "get_amount_step": get_amount_step,
            "get_identity_settings": get_identity_settings,
            "get_user_payment_settings": get_user_payment_settings,
        }

    # Register Blueprints
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(user, url_prefix="/user")
    app.register_blueprint(pay, url_prefix="/pay")
    app.register_blueprint(api, url_prefix="/api")
    app.register_blueprint(landing, url_prefix="/")

    # Global 404 Error Handler
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    # Start the scheduler
    from app.jobs import get_services, update_prices, update_discount

    scheduler.add_job(
        id="get_services",
        func=get_services,
        args=[app],
        trigger="cron",
        hour="7,19",  # Runs twice daily at 1:25 AM (01:25) and 1:25 PM (13:25) in 24-hour format
        minute=30,
        timezone="Asia/Dhaka",
        replace_existing=True,
        misfire_grace_time=20,
    )
    scheduler.add_job(
        id="update_prices",
        func=update_prices,
        args=[app],
        trigger="cron",
        second=3,
        timezone="Asia/Dhaka",
        replace_existing=True,
        misfire_grace_time=20,
    )
    scheduler.add_job(
        id="update_discount",
        func=update_discount,
        args=[app],
        trigger="cron",
        second=3,
        timezone="Asia/Dhaka",
        replace_existing=True,
        misfire_grace_time=20,
    )

    return app
