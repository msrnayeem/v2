from pydoc import isdata
from flask import Blueprint, jsonify, request
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import aiohttp
import asyncio
from app.helpers.middleware import is_active, is_auth, is_verified, is_user, is_admin
from app.helpers.authdata import auth_data
from app.utils.table import CRUD
from dotenv import load_dotenv
import os

api = Blueprint("api", __name__)
load_dotenv()

# Create a thread pool executor
executor = ThreadPoolExecutor(max_workers=10)


# Decorator to run async functions in a separate thread
def async_route(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(f(*args, **kwargs))
            return result
        finally:
            loop.close()

    return wrapper


# load environment variables
BASE_URL = os.getenv("BASE_URL")


# generate bearer token async
async def generate_bearer_token(server):
    headers = {"X-API-KEY": server.get("api"), "X-API-USERNAME": server.get("email")}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/api/pub/v2/auth", headers=headers
            ) as response:
                response.raise_for_status()
                token_data = await response.json()
                return token_data.get("token")
    except Exception as e:
        print(f"Error generating token: {e}")
        return None


# async function for API requests
async def make_api_request(
    server, endpoint, method="GET", data=None, params=None, urltype=None
):
    token = await generate_bearer_token(server)
    if not token:
        return {"error": "Failed to generate token"}

    url = endpoint if urltype else f"{BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with aiohttp.ClientSession() as session:
            if method.upper() == "GET":
                async with session.get(url, headers=headers, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            elif method.upper() == "POST":
                async with session.post(url, headers=headers, json=data) as response:
                    response.raise_for_status()
                    return await response.json()
            else:
                return {"error": f"Unsupported HTTP method: {method}"}
    except Exception as e:
        print(f"Error making API request: {e}")
        return {"error": f"API request failed: {str(e)}"}


@api.route("/createverification", methods=["POST"])
@is_auth
@is_verified
@is_user
@is_active
@async_route
async def createverification():
    try:
        model = CRUD("verifications")
        user_id = auth_data().get("data").get("id")

        # validate data
        service_id = request.json.get("service_id")
        server_id = request.json.get("server_id")
        service_name = request.json.get("service_name")

        if not all([service_id, server_id]):
            return jsonify({"status": "error", "message": "All fields are required"})

        # validate service id
        service = CRUD("services").where(id=service_id, status="on")
        if not service or not service.get("data"):
            return jsonify({"status": "error", "message": "Invalid service ID"})
        service_data = service.get("data")[0]

        # check is valid server or not
        server = CRUD("servers").get_by_column("id", server_id)
        server_data = {}
        if server.get("status") == "success":
            if not server.get("data").get("api") or not server.get("data").get("email"):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Server error. Please contact with admin",
                    }
                )
            else:
                server_data = server.get("data")
        else:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        # check already running any services
        check = model.where(user_id=user_id, status="pending")
        if check and check.get("data"):
            return jsonify(
                {
                    "status": "error",
                    "message": "You already have a pending verification",
                }
            )

        # check balance
        service_price = (
            service_data.get("selling_price")
            if service_data.get("selling_price")
            else service_data.get("price")
        )
        if service_price > auth_data().get("data").get("coin"):
            return jsonify(
                {
                    "status": "error",
                    "message": "Insufficient balance. Please recharge your account. <a href='/user/creadits' class='underline'>Deposit</a>",
                }
            )

        # Prepare the body for the verification request
        body = {
            "areaCodeSelectOption": service_data.get("areaCodeSelectOption", []),
            "carrierSelectOption": service_data.get("carrierSelectOption", []),
            "serviceName": service_data.get("service", ""),
            "capability": service_data.get("capacity", ""),
            "serviceNotListedName": service_data.get("serviceNotListedName", ""),
        }

        result = await make_api_request(
            server_data, "/api/pub/v2/verifications", method="POST", data=body
        )

        if result and not result.get("error"):
            verification_id = (
                result.get("href", "").split("/")[-1] if result.get("href") else None
            )
            endpoint = f"/api/pub/v2/verifications/{verification_id}"
            polling_data = await make_api_request(server_data, endpoint, method="GET")

            # service name
            newservice_name = ""
            if service_name:
                newservice_name = service_name
            else:
                newservice_name = service_data.get("service")

            if polling_data and not polling_data.get("error"):
                store = model.create(
                    service_id=service_id,
                    user_id=user_id,
                    service_name=newservice_name,
                    price=service_price,
                    server_id=server_id,
                    service_token=verification_id,
                    number=polling_data.get("number"),
                    created_at=polling_data.get("createdAt"),
                    endsAt=polling_data.get("endsAt"),
                )

                if store.get("status") == "success":
                    # update user balance
                    new_balance = auth_data().get("data").get("coin") - service_price
                    CRUD("users").update(
                        auth_data().get("data").get("id"), coin=new_balance
                    )
                    return jsonify(
                        {
                            "status": "success",
                            "message": "Verification created successfully",
                            "data": model.get_by_column("id", store.get("data")).get(
                                "data"
                            ),
                        }
                    )

        return jsonify(
            {
                "status": "error",
                "message": "Failed to create verification. Please try again!",
            }
        )

    except Exception as e:
        print(f"Error in createverification: {e}")
        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )


@api.route("/otp", methods=["POST"])
@is_auth
@is_verified
@is_user
@is_active
@async_route
async def otp():
    try:
        id = request.json.get("id")
        if not id:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        model_data = CRUD("verifications").get_by_column("id", id).get("data")
        if not model_data:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        # check is valid server or not
        server = CRUD("servers").get_by_column("id", model_data.get("server_id"))
        server_data = {}
        if server.get("status") == "success":
            if not server.get("data").get("api") or not server.get("data").get("email"):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Server error. Please contact with admin",
                    }
                )
            else:
                server_data = server.get("data")
        else:
            return jsonify(
                {
                    "status": "error",
                    "message": "Server error. Please try again later!",
                }
            )

        endpoint = f"/api/pub/v2/sms?ReservationId={model_data.get('service_token')}"
        otpdata = await make_api_request(server_data, endpoint, method="GET")

        if otpdata and not otpdata.get("error") and otpdata.get("data"):
            CRUD("verifications").update(
                id,
                opt=otpdata.get("data")[0].get("parsedCode"),
                status="complete",
                sms=otpdata.get("data")[0].get("smsContent"),
            )
            return jsonify(CRUD("verifications").get_by_column("id", id))

        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )

    except Exception as e:
        print(f"Error in otp: {e}")
        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )


@api.route("/cancel", methods=["POST"])
@is_auth
@is_verified
@is_user
@is_active
@async_route
async def cancel():
    try:
        model = CRUD("verifications")
        id = request.json.get("id")
        if not id:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        v_data = model.get_by_column("id", id).get("data")
        if not v_data:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        # check already cancele or no
        if v_data.get("status") == "cancel":
            return jsonify(
                {
                    "status": "error",
                    "message": "The service already canceled!",
                    "order": "success",
                    "data": CRUD("verifications").get_by_column("id", id),
                }
            )

        # check is valid server or not
        server = CRUD("servers").get_by_column("id", v_data.get("server_id"))
        server_data = {}
        if server.get("status") == "success":
            if not server.get("data").get("api") or not server.get("data").get("email"):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Server error. Please contact with admin",
                    }
                )
            else:
                server_data = server.get("data")
        else:
            return jsonify(
                {
                    "status": "error",
                    "message": "Server error. Please try again later!",
                }
            )

        endpoint = f"/api/pub/v2/verifications/{v_data.get('service_token')}/cancel"
        res_data = await make_api_request(server_data, endpoint, method="POST")

        if res_data:
            CRUD("verifications").update(
                id,
                status="cancel",
            )
            new_balance = auth_data().get("data").get("coin") + v_data.get("price")
            CRUD("users").update(auth_data().get("data").get("id"), coin=new_balance)
            return jsonify(
                {
                    "status": "success",
                    "message": "Cancellation was successful",
                    "data": CRUD("verifications").get_by_column("id", id),
                }
            )

        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )

    except Exception as e:
        print(f"Error in cancel: {e}")
        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )


@api.route("getdata", methods=["POST"])
@is_auth
@is_verified
@is_user
@is_active
@async_route
async def getdata():
    try:
        model = CRUD("verifications")
        id = request.json.get("id")
        if not id:
            return jsonify(
                {
                    "status": "error",
                    "message": "Something wrong. Try again! Or reload the page.",
                }
            )
        return jsonify(
            {"status": "success", "data": model.get_by_column("id", id).get("data")}
        )
    except Exception as e:
        print(f"Error in getdata: {e}")
        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )


@api.route("/timeout", methods=["POST"])
@is_auth
@is_verified
@is_user
@is_active
@async_route
async def timeout():
    try:
        id = request.json.get("id")
        model = CRUD("verifications").update(id, status="timeout")
        if model:
            return jsonify(
                {"status": "success", "message": "Ops! your service are timeout"}
            )
        return jsonify({"status": "error", "message": "Server error"})
    except Exception as e:
        print(f"Error in timeout: {e}")
        return jsonify({"status": "error", "message": "Server error"})


@api.route("/serverdetails", methods=["POST"])
@is_auth
@is_verified
@is_admin
@is_active
@async_route
async def serverdetails():
    try:
        server_id = request.json.get("id")
        if not server_id:
            return jsonify({"status": "error", "message": "Server ID is required"})

        # check is valid server or not
        server = CRUD("servers").get_by_column("id", server_id)
        server_data = {}
        if server.get("status") == "success":
            if not server.get("data").get("api") or not server.get("data").get("email"):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Server error. Please contact with admin",
                    }
                )
            else:
                server_data = server.get("data")
        else:
            return jsonify(
                {
                    "status": "error",
                    "message": "Server error. Please try again later!",
                }
            )

        endpoint = f"/api/pub/v2/account/me"
        res_data = await make_api_request(server_data, endpoint, method="GET")

        if res_data and not res_data.get("error"):
            return jsonify(
                {
                    "status": "success",
                    "data": res_data,
                }
            )

        return jsonify(
            {
                "status": "error",
                "message": "Server error. Please try again later!",
            }
        )
    except Exception as e:
        print(f"Error in serverdetails: {e}")
        return jsonify({"status": "error", "message": "Server error try again!"})


@api.route("/price", methods=["POST"])
@async_route
async def price():
    try:
        model = CRUD("services")
        id = request.json.get("id")
        if not id:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        v_data = model.get_by_column("id", id).get("data")
        if not v_data:
            return jsonify(
                {"status": "error", "message": "Server error. Please try again later!"}
            )

        # check is valid server or not
        server = CRUD("servers").first().get("data")
        endpoint = f"/api/pub/v2/pricing/verifications"
        body = {
            "serviceName": v_data.get("service"),
            "areaCode": True,
            "carrier": True,
            "numberType": "mobile",
            "capability": "sms",
        }
        res_data = await make_api_request(server, endpoint, method="POST", data=body)

        if res_data and not res_data.get("error"):
            model.update(id, price=res_data.get("price"))
            return jsonify(
                {
                    "status": "success",
                    "data": res_data.get("price"),
                    "old": model.get_by_column("id", id),
                }
            )

        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )
    except Exception as e:
        print(f"Error in price: {e}")
        return jsonify(
            {"status": "error", "message": "Server error. Please try again later!"}
        )


# get all services
@api.route("/services_from_server")
@async_route
async def services_from_server():
    try:
        server = CRUD("servers").first().get("data")
        if not server:
            return jsonify(
                {"status": "error", "message": "Server configuration not found"}
            )

        endpoint = "/api/pub/v2/services"
        params = {
            "numberType": "mobile",  # mobile, voip, landline
            "reservationType": "verification",  # renewable, nonrenewable, verification
        }

        res_data = await make_api_request(server, endpoint, method="GET", params=params)
        if res_data and isinstance(res_data, list):
            res_data = [
                service
                for service in res_data
                if service.get("capability", "").lower() == "sms"
            ]
        if res_data:
            return jsonify(
                {
                    "status": "success",
                    "data": res_data,
                }
            )
        else:
            return jsonify({"status": "error", "message": "Server error try again!"})

    except Exception as e:
        print(f"Error in services_from_server: {e}")
        return jsonify({"status": "error", "message": f"API request failed: {str(e)}"})

