from datetime import datetime
from anyio import sleep
from app.utils.table import CRUD
from app import db
from flask import g
import requests

def update_prices(app):
    with app.app_context():
        g.db = db
        row = CRUD("services")

        null_prices_service = row.get_by_column("price", 0)

        if not null_prices_service or not null_prices_service.get("data"):
            print("⚠️ No service found with price 0")
            return

        service_data = null_prices_service.get("data")
        service_id = service_data.get("id")
        service_name = service_data.get("service")

        if not service_id:
            print("❌ Service ID missing in data")
            return

        # Example: You may call an external API to get price
        try:
            response = requests.post(
                "https://example.com/get-price",
                json={"id": service_id},
                timeout=10
            )
            response.raise_for_status()
            result = response.json()

            new_price = result.get("price")
            if new_price is not None:
                update_price(app, new_price, service_id)
            else:
                print(f"⚠️ Price not found in response for service {service_name}")
        except Exception as e:
            print(f"❌ Error fetching price for service {service_name}: {e}")

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


def update_discount(app):
    with app.app_context():
        g.db = db

        # Fetch the current discount
        discount_record = CRUD("discount").first()
        if not discount_record or not discount_record.get("data"):
            make_logs(app, "⚠️ No discount found.")
            return

        discount_value = discount_record["data"].get("value")
        if discount_value is None:
            make_logs(app, "⚠️ Discount value is missing.")
            return

        # Fetch service that doesn't already have this discount
        service_model = CRUD("services")
        discount_code = service_model.notwhere_single(discount=discount_value)

        if not discount_code or discount_code.get("status") != "success" or not discount_code.get("data"):
            make_logs(app, "ℹ️ No matching service found for discount update.")
            return

        service_data = discount_code["data"]
        service_id = service_data.get("id")
        service_name = service_data.get("serviceName")
        current_discount = service_data.get("discount")
        price = service_data.get("price")
        discount_status = service_data.get("discount_status")

        if price is None or service_id is None:
            make_logs(app, f"⚠️ Invalid service data for {service_name or 'unknown service'}.")
            return

        if current_discount != discount_value:
            try:
                discount_price = float(price) * (1 - float(discount_value) / 100)
            except (TypeError, ValueError):
                make_logs(app, f"❌ Failed to calculate discount price for {service_name}.")
                return

            if discount_status == "on":
                service_model.update(
                    service_id,
                    discount=discount_value,
                    selling_price=discount_price,
                )
                make_logs(
                    app,
                    f"✅ Discount code updated for {service_name} to {discount_value}%",
                )
            else:
                make_logs(
                    app,
                    f"⚠️ Auto discount is OFF for {service_name}.",
                )
        else:
            make_logs(
                app,
                f"ℹ️ Discount already applied to {service_name}, no update needed.",
            )
