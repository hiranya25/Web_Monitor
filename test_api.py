from dotenv import load_dotenv

from app.audits.backlinks import fetch_backlink_data
from app.audits.traffic_trends import fetch_traffic_data

load_dotenv()


if __name__ == "__main__":
    domain = "amipi.com"
    print("Backlinks:", fetch_backlink_data(domain))
    print("Traffic:", fetch_traffic_data(domain))
