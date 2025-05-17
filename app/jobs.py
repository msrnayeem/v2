from datetime import datetime
from anyio import sleep
from app.utils.table import CRUD
from app import db
from flask import g
import requests

def update_price(app, data, service_id):
    with app.app_context():
        g.db = db
        row = CRUD("services")
        discount_code = CRUD("discount").first()

        current_price_result = row.get_by_column("id", service_id)
        current_price = current_price_result.get("data") if current_price_result else None

        if current_price is None:
            print(f"No service found with id {service_id}")
            return

        discount_value = None
        if discount_code:
            discount_data = discount_code.get("data") if discount_code else None
            if discount_data:
                discount_value = discount_data.get("value")

        try:
            current_price_float = float(current_price.get("price", 0))
            new_price_float = float(data)
        except (TypeError, ValueError):
            print(f"Invalid price data for service id {service_id}")
            return

        if current_price_float != new_price_float:
            if discount_value:
                try:
                    discount_float = float(discount_value)
                    discount_price = new_price_float * (1 - discount_float / 100)
                except (TypeError, ValueError):
                    discount_price = new_price_float
            else:
                discount_price = new_price_float

            row.update(
                service_id,
                price=discount_price,
                updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            print(f"Price updated for {current_price.get('service')}")
        else:
            row.update(
                service_id,
                updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            print(f"Price not updated for {current_price.get('service')}")

# make logs
def make_logs(app, data):
    with app.app_context():
        g.db = db
        row = CRUD("logs")
        row.create(
            text=data,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


# interval example
def get_services(app):
    with app.app_context():
        g.db = db
        # get services from server
        row = CRUD("services")
        row.deldublicate()
        make_logs(app, "Dublicate services deleted")
        services_from_server = requests.get(
            f"{app.config['APP_URL']}/api/services_from_server"
        ).json()
        if services_from_server:
            for service in services_from_server.get("data"):
                # check if service exists
                service_exists = row.get_by_column(
                    "service", service.get("serviceName")
                )
                if service_exists.get("status") == "success" and service_exists.get(
                    "data"
                ):
                    print(f"Service {service.get('serviceName')} already exists")
                else:
                    CRUD("services").create(
                        service=service.get("serviceName"),
                        status="on",
                        created_at=datetime.now(),  # type: ignore
                        updated_at=datetime.now(),  # type: ignore
                    )
                    make_logs(app, f"Service {service.get('serviceName')} created")
            else:
                make_logs(app, "All services from server are already in the database")
        else:
            make_logs(app, "No services from server")


# update prices
def update_prices(app):
    with app.app_context():
        g.db = db
        # get null prices service
        row = CRUD("services")
        null_prices_service = row.get_one_not_updated_now()
        if null_prices_service:
            try:
                res = requests.post(
                    f'{app.config["APP_URL"]}/api/price',
                    json={"id": null_prices_service.get("data").get("id")},
                    timeout=10,
                ).json()
                if res.get("status") == "success":
                    update_price(
                        app, res.get("data"), null_prices_service.get("data").get("id")
                    )
                    make_logs(
                        app,
                        f"Price updated for {null_prices_service.get('data').get('service')}",
                    )
            except requests.exceptions.RequestException as e:
                make_logs(app, f"Error making price update request: {e}")
                res = {"status": "error", "message": "Request failed"}
        else:
            make_logs(app, "I hope you have no null prices service")


# update discout
def update_discount(app):
    with app.app_context():
        g.db = db
        update_discount = CRUD("discount").first()
        model = CRUD("services")
        discount_code = model.notwhere_single(
            discount=update_discount.get("data").get("value")
        )
        if discount_code.get("status") == "success":
            if discount_code.get("data").get("discount") != update_discount.get(
                "data"
            ).get("value"):
                discount_price = float(discount_code.get("data").get("price")) * (
                    1 - float(update_discount.get("data").get("value")) / 100
                )
                if discount_code.get("discount_status") == "on":
                    model.update(
                        discount_code.get("data").get("id"),
                        discount=update_discount.get("data").get("value"),
                        selling_price=discount_price,
                    )
                    make_logs(
                        app,
                        f"Discount code updated for {discount_code.get('data').get('serviceName')} to {update_discount.get('data').get('value')}",
                    )
                else:
                    make_logs(
                        app,
                        f"Auto discount code {discount_code.get('data').get('serviceName')} is off",
                    )
            else:
                make_logs(
                    app,
                    f"Discount code not updated for {discount_code.get('data').get('serviceName')}",
                )
        else:
            make_logs(app, "I hope you have no discount code")