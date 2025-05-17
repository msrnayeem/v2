import time
from flask import (
    Blueprint,
    jsonify,
    url_for,
    redirect,
    request,
    render_template,
    flash,
)
import stripe
import paypalrestsdk
import requests
from app.helpers.middleware import is_auth, is_verified, is_user, is_active
from app.helpers.authdata import auth_data
from app.helpers.settings import get_stripe_data, get_paypal_data, get_crypto_data
from app.utils.table import CRUD

pay = Blueprint("pay", __name__)


# Get base url
def get_base_url():
    return request.url_root.rstrip("/")


# Update user balance
def _update_user_balance(user_id, amount):
    """Helper function to update user's coin balance"""
    user_model = CRUD("users")
    current_coin = auth_data().get("data").get("coin", 0)
    if amount > 0:
        new_coin = current_coin + float(amount)
        return user_model.update(user_id, coin=new_coin)


# Record transaction
def _record_transaction(gateway, payment_status, amount, payment_id):
    """Helper function to record transaction in database"""
    user_data = auth_data().get("data")
    model = CRUD("transactions")

    # Check if transaction already exists
    existing_tx = model.count(pay_id=payment_id)

    if (
        existing_tx.get("status") == "success"
        and existing_tx.get("data") <= 0
        and amount > 0
    ):
        _update_user_balance(auth_data().get("data").get("id"), amount)
        return model.create(
            user_name=user_data.get("name"),
            user_id=user_data.get("id"),
            amount=amount,
            type=gateway,
            type_details=f"Pay by {gateway}",
            status=payment_status.lower(),
            pay_id=payment_id,
        )
    return None


# Create payment session
@pay.route("/session", methods=["POST"])
@is_auth
@is_verified
@is_user
@is_active
def create_payment_session():
    stripe_data = get_stripe_data()
    paypal_data = get_paypal_data()
    crypto_data = get_crypto_data()

    # Initialize payment gateways
    if stripe_data.get("secret_key") and stripe_data.get("publishable_key"):
        stripe.api_key = stripe_data.get("secret_key")
    else:
        return jsonify(
            {"status": "error", "message": "Server error plase contact with admin"}
        )

    if paypal_data.get("client_id") and paypal_data.get("secret_key"):
        paypalrestsdk.configure(
            {
                "mode": "live",  # Change to 'live/sandbox' for production
                "client_id": paypal_data.get("client_id"),
                "client_secret": paypal_data.get("secret_key"),
            }
        )
    else:
        return jsonify(
            {
                "status": "error",
                "message": "Server error plase contact with admin",
            }
        )

    if not crypto_data.get("api_key"):
        return jsonify(
            {"status": "error", "message": "Server error plase contact with admin"}
        )

    data = request.json
    gateway = data.get("gateway")
    amount = data.get("amount")
    currency = data.get("currency", "usd")
    base_url = get_base_url()

    if not amount or not gateway:
        return jsonify({"error": "Amount and gateway are required"})

    try:
        if gateway == "stripe":
            return create_stripe_session(amount, currency, base_url)
        elif gateway == "paypal":
            return create_paypal_order(amount, currency, base_url)
        elif gateway == "crypto":
            crypto_currency = data.get("crypto_currency")
            if not crypto_currency:
                return jsonify(
                    {"status": "error", "message": "Please select a crypto currency"}
                )
            return create_crypto_order(amount, currency, base_url, crypto_currency)
        else:
            return jsonify({"error": "Invalid payment gateway"})
    except Exception as e:
        return jsonify({"error": "Server error try again later or reload the page"})


# Stripe
def handle_stripe_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return redirect(url_for("user.creadits"))

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        payment_status = session.get("payment_status")
        amount_total = session.get("amount_total", 0) / 100
        currency = session.get("currency", "usd").upper()
        payment_id = session.get("payment_intent")

        # Record transaction and update balance
        _record_transaction("stripe", payment_status, amount_total, payment_id)

        return render_success_page(payment_status, amount_total, currency, "Stripe")
    except stripe.error.StripeError:
        return redirect(url_for("user.creadits"))


# Paypal
def handle_paypal_success():
    order_id = request.args.get("paymentId")
    payer_id = request.args.get("PayerID")

    if not order_id or not payer_id:
        return redirect(url_for("user.creadits"))

    try:
        order = paypalrestsdk.Payment.find(order_id)

        # Execute the payment
        if not order.execute({"payer_id": payer_id}):
            print("Failed to execute PayPal payment")
            return redirect(url_for("user.creadits"))

        payment_status = order.state
        amount_total = float(order.transactions[0].amount.total)
        currency = order.transactions[0].amount.currency.upper()
        payment_id = order_id
        status = (
            "Paid"
            if payment_status in ["approved", "completed", "executed"]
            else "cancel"
        )

        # Record transaction and update balance
        _record_transaction("paypal", status, amount_total, payment_id)

        return render_success_page(status, amount_total, currency, "Paypal")

    except Exception as e:
        print("PayPal Error:", str(e))
        return redirect(url_for("user.creadits"))


# handle crypto
def handle_crypto_ssuccess(amount, curency, pay_id):
    # Record transaction and update balance
    _record_transaction("paypal", "paid", amount, pay_id)

    return render_success_page("paid", amount, curency, "Crypto")


# Success ========
def render_success_page(payment_status, amount, currency, methods):
    return render_template(
        "pay/success.html",
        data={
            "message": "Payment successful",
            "payment_status": payment_status,
            "amount_total": amount,
            "currency": currency,
            "methods": methods,
        },
    )


# Cancel
@pay.route("/cancel")
@is_auth
@is_verified
@is_user
@is_active
def cancel():
    return render_template("pay/failed.html")


# Success
@pay.route("/success", methods=["GET"])
@is_auth
@is_verified
@is_user
@is_active
def success():
    gateway = request.args.get("gateway")

    if gateway == "stripe":
        return handle_stripe_success()
    elif gateway == "paypal":
        return handle_paypal_success()

    return redirect(url_for("user.creadits"))


# ipn
@pay.route("/ipn", methods=["GET"])
def ipn():
    try:
        order_id = request.args.get("order_id")
        if not order_id:
            flash("Order ID is required", "error")
            return redirect(url_for("user.creadits"))

        # get payment status
        crypto_data = get_crypto_data()
        if not crypto_data or not crypto_data.get("api_key"):
            flash("Payment configuration error", "error")
            return redirect(url_for("user.creadits"))

        url = f"https://api.nowpayments.io/v1/payment/{order_id}"
        payload = {}
        headers = {"x-api-key": crypto_data.get("api_key")}
        response = requests.request("GET", url, headers=headers, data=payload)

        try:
            payment_status = response.json()
        except ValueError:
            flash("Invalid payment response", "error")
            return redirect(url_for("user.creadits"))

        # if success
        if payment_status.get("payment_status") == "finished":
            handle_crypto_ssuccess(
                payment_status.get("actually_paid"),
                payment_status.get("pay_currency"),
                payment_status.get("payment_id"),
            )
            return

        return render_template(
            "pay/ipn.html",
            data=payment_status,
        )
    except requests.exceptions.RequestException as e:
        print(f"IPN Request Error: {str(e)}")
        flash("Payment service unavailable, please try again later", "error")
        return redirect(url_for("user.creadits"))
    except Exception as e:
        print(f"IPN Error: {str(e)}")
        flash("Server error try again later or reload the page", "error")
        return redirect(url_for("user.creadits"))


# Stripe
def create_stripe_session(amount, currency, base_url):
    try:
        amount_in_cents = int(float(amount) * 100)
        user_data = auth_data().get("data")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "product_data": {"name": "Token Purchase"},
                        "unit_amount": amount_in_cents,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            customer_email=user_data.get("email"),
            metadata={
                "name": user_data.get("name"),
                "user_id": user_data.get("id"),
            },
            success_url=f"{base_url}/pay/success?session_id={{CHECKOUT_SESSION_ID}}&gateway=stripe",
            cancel_url=f"{base_url}/pay/cancel",
        )
        return jsonify({"status": "success", "id": session.id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# Paypal
def create_paypal_order(amount, currency, base_url):
    try:
        amount = float(amount)
        # First create the payment without the order_id in return_url
        payment = paypalrestsdk.Payment(
            {
                "intent": "sale",
                "payer": {"payment_method": "paypal"},
                "transactions": [
                    {
                        "amount": {
                            "total": f"{amount:.2f}",
                            "currency": currency.upper(),
                        },
                        "description": "Token purchase",
                    }
                ],
                "redirect_urls": {
                    "return_url": f"{base_url}/pay/success?gateway=paypal",
                    "cancel_url": f"{base_url}/pay/cancel",
                },
            }
        )

        if payment.create():
            # After creation, we can access payment.id
            # Update the return_url with the order_id
            approval_url = next(
                (
                    link.href.replace(
                        f"{base_url}/pay/success?gateway=paypal",
                        f"{base_url}/pay/success?gateway=paypal&order_id={payment.id}",
                    )
                    for link in payment.links
                    if link.rel == "approval_url"
                ),
                None,
            )

            if approval_url:
                return jsonify(
                    {
                        "status": "success",
                        "approval_url": approval_url,
                        "order_id": payment.id,
                    }
                )

        return jsonify(
            {
                "status": "error",
                "message": (
                    payment.error.get("message", "Failed to create PayPal payment")
                    if payment.error
                    else "Failed to create PayPal payment"
                ),
            }
        )

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# crypto
def create_crypto_order(amount, currency, base_url, crypto_currency):
    try:
        crypto_data = get_crypto_data()
        url = "https://api.nowpayments.io/v1/payment"
        headers = {
            "x-api-key": crypto_data.get("api_key", ""),
            "Content-Type": "application/json",
        }
        data = {
            "price_amount": float(amount),  # e.g. 50.0
            "price_currency": currency.lower(),  # e.g. 'usd'
            "pay_currency": crypto_currency,
            "ipn_callback_url": f"{base_url}/pay/ipn",
            "order_description": "Token purchase",
            "order_id": f"order_{int(time.time())}",
        }
        response = requests.post(url, json=data, headers=headers)
        payment = response.json()
        if payment.get("payment_id"):
            return jsonify(
                {
                    "status": "success",
                    "approval_url": f"{base_url}/pay/ipn",
                    "order_id": payment.get("payment_id"),
                }
            )
        else:
            return jsonify(
                {
                    "status": "error",
                    "message": "Server error. Please reload the page or try using a different cryptocurrency.",
                }
            )
    except requests.exceptions.RequestException as e:
        return jsonify(
            {
                "status": "error",
                "message": "Server error plase reload the page and try again!",
            }
        )
