from app.utils.table import CRUD


def get_seo_settings():
    model = CRUD("seo")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data


def get_smtp_settings():
    model = CRUD("smtp")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data


def get_stripe_data():
    model = CRUD("stripe")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data


def get_paypal_data():
    model = CRUD("paypal")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data


def get_crypto_data():
    model = CRUD("crypto")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data


def get_amount_step():
    amount_step = CRUD("amount_step").order_by_small_value("amount")
    data = {}
    if amount_step:
        data = amount_step.get("data", {})
    return data


def get_identity_settings():
    model = CRUD("identity")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data

def get_user_payment_settings():
    model = CRUD("credit_status")
    data = {}
    if model.first():
        data = model.first().get("data", {})
    return data

