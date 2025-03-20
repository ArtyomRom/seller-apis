import datetime
import logging.config

import requests
from environs import Env

from seller import divide, price_conversion
from seller import download_stock

logger = logging.getLogger(__file__)


def get_product_list(page, campaign_id, access_token):
    """Получает список товаров из Яндекс Маркета.

        Args:
            page (str): Токен страницы для пагинации.
            campaign_id (str): ID кампании в Яндекс Маркете.
            access_token (str): Токен авторизации API.

        Returns:
            dict: Результат запроса с товарами.
    """
    endpoint_url = "https://api.partner.market.yandex.ru/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Host": "api.partner.market.yandex.ru",
    }
    payload = {
        "page_token": page,
        "limit": 200,
    }
    url = endpoint_url + f"campaigns/{campaign_id}/offer-mapping-entries"
    response = requests.get(url, headers=headers, params=payload)
    response.raise_for_status()
    response_object = response.json()
    return response_object.get("result")


def update_stocks(stocks, campaign_id, access_token):
    """Обновляет остатки товаров в Яндекс Маркете.

        Args:
            stocks (list): Список остатков товаров.
            campaign_id (str): ID кампании в Яндекс Маркете.
            access_token (str): Токен авторизации API.

        Returns:
            dict: Ответ API.
    """
    endpoint_url = "https://api.partner.market.yandex.ru/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Host": "api.partner.market.yandex.ru",
    }
    payload = {"skus": stocks}
    url = endpoint_url + f"campaigns/{campaign_id}/offers/stocks"
    response = requests.put(url, headers=headers, json=payload)
    response.raise_for_status()
    response_object = response.json()
    return response_object


def update_price(prices, campaign_id, access_token):
    """Обновляет цены товаров в Яндекс Маркете.

        Args:
            prices (list): Список цен товаров.
            campaign_id (str): ID кампании в Яндекс Маркете.
            access_token (str): Токен авторизации API.

        Returns:
            dict: Ответ API.
    """
    endpoint_url = "https://api.partner.market.yandex.ru/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Host": "api.partner.market.yandex.ru",
    }
    payload = {"offers": prices}
    url = endpoint_url + f"campaigns/{campaign_id}/offer-prices/updates"
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    response_object = response.json()
    return response_object


def get_offer_ids(campaign_id, market_token):
    """Получить артикулы товаров Яндекс маркета.

        Args:
            campaign_id (str): ID кампании в Яндекс Маркете.
            market_token (str): Токен авторизации API.

        Returns:
            list: Список артикулов товаров.
    """
    page = ""
    product_list = []
    while True:
        some_prod = get_product_list(page, campaign_id, market_token)
        product_list.extend(some_prod.get("offerMappingEntries"))
        page = some_prod.get("paging").get("nextPageToken")
        if not page:
            break
    offer_ids = []
    for product in product_list:
        offer_ids.append(product.get("offer").get("shopSku"))
    return offer_ids


def create_stocks(watch_remnants, offer_ids, warehouse_id):
    """Создаёт список остатков товаров для загрузки в Маркет.

    Args:
        watch_remnants (list): Остатки товаров.
        offer_ids (list): Артикулы товаров.
        warehouse_id (str): ID склада.

    Returns:
        list: Список остатков товаров в формате API Маркета.
    """
    # Уберем то, что не загружено в market
    stocks = list()
    date = str(datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    for watch in watch_remnants:
        if str(watch.get("Код")) in offer_ids:
            count = str(watch.get("Количество"))
            if count == ">10":
                stock = 100
            elif count == "1":
                stock = 0
            else:
                stock = int(watch.get("Количество"))
            stocks.append(
                {
                    "sku": str(watch.get("Код")),
                    "warehouseId": warehouse_id,
                    "items": [
                        {
                            "count": stock,
                            "type": "FIT",
                            "updatedAt": date,
                        }
                    ],
                }
            )
            offer_ids.remove(str(watch.get("Код")))
    # Добавим недостающее из загруженного:
    for offer_id in offer_ids:
        stocks.append(
            {
                "sku": offer_id,
                "warehouseId": warehouse_id,
                "items": [
                    {
                        "count": 0,
                        "type": "FIT",
                        "updatedAt": date,
                    }
                ],
            }
        )
    return stocks


def create_prices(watch_remnants, offer_ids):
    """Создаёт список цен для загрузки в Маркет.

        Args:
            watch_remnants (list): Остатки товаров.
            offer_ids (list): Артикулы товаров.

        Returns:
            list: Список цен в формате API Маркета.
    """
    prices = []
    for watch in watch_remnants:
        if str(watch.get("Код")) in offer_ids:
            price = {
                "id": str(watch.get("Код")),
                # "feed": {"id": 0},
                "price": {
                    "value": int(price_conversion(watch.get("Цена"))),
                    # "discountBase": 0,
                    "currencyId": "RUR",
                    # "vat": 0,
                },
                # "marketSku": 0,
                # "shopSku": "string",
            }
            prices.append(price)
    return prices


async def upload_prices(watch_remnants, campaign_id, market_token):
    """
        Загрузка цен для предложений в кампанию.

        Эта функция получает идентификаторы предложений для указанной кампании,
        затем создает и обновляет цены для предложений в этой кампании, отправляя
        данные пакетами по 500 предложений.

        Args:
            watch_remnants (list): Список остатков, который содержит данные для обновления цен.
            campaign_id (str): Идентификатор кампании, для которой обновляются цены.
            market_token (str): Токен для доступа к маркетплейсу, необходим для обновления цен.

        Return:
            list: Список всех цен, созданных для предложений.
        """
    offer_ids = get_offer_ids(campaign_id, market_token)
    prices = create_prices(watch_remnants, offer_ids)
    for some_prices in list(divide(prices, 500)):
        update_price(some_prices, campaign_id, market_token)
    return prices


async def upload_stocks(watch_remnants, campaign_id, market_token, warehouse_id):
    """
       Загрузка остатков для предложений в кампанию.

       Эта функция получает идентификаторы предложений для указанной кампании,
       создает и обновляет остатки товаров на складе, отправляя данные пакетами
       по 2000 предложений. После загрузки остатков возвращает только те остатки,
       у которых количество товаров не равно нулю.

       Args:
           watch_remnants (list): Список остатков, который содержит данные для обновления остатков.
           campaign_id (str): Идентификатор кампании, для которой обновляются остатки.
           market_token (str): Токен для доступа к маркетплейсу, необходим для обновления остатков.
           warehouse_id (str): Идентификатор склада, на котором хранятся товары.

       Return:
           tuple:
               - list: Список остатков, в которых количество товаров больше нуля.
               - list: Все остатки товаров для предложений.
       """
    offer_ids = get_offer_ids(campaign_id, market_token)
    stocks = create_stocks(watch_remnants, offer_ids, warehouse_id)
    for some_stock in list(divide(stocks, 2000)):
        update_stocks(some_stock, campaign_id, market_token)
    not_empty = list(
        filter(lambda stock: (stock.get("items")[0].get("count") != 0), stocks)
    )
    return not_empty, stocks


def main():
    env = Env()
    market_token = env.str("MARKET_TOKEN")
    campaign_fbs_id = env.str("FBS_ID")
    campaign_dbs_id = env.str("DBS_ID")
    warehouse_fbs_id = env.str("WAREHOUSE_FBS_ID")
    warehouse_dbs_id = env.str("WAREHOUSE_DBS_ID")

    watch_remnants = download_stock()
    try:
        # FBS
        offer_ids = get_offer_ids(campaign_fbs_id, market_token)
        # Обновить остатки FBS
        stocks = create_stocks(watch_remnants, offer_ids, warehouse_fbs_id)
        for some_stock in list(divide(stocks, 2000)):
            update_stocks(some_stock, campaign_fbs_id, market_token)
        # Поменять цены FBS
        upload_prices(watch_remnants, campaign_fbs_id, market_token)

        # DBS
        offer_ids = get_offer_ids(campaign_dbs_id, market_token)
        # Обновить остатки DBS
        stocks = create_stocks(watch_remnants, offer_ids, warehouse_dbs_id)
        for some_stock in list(divide(stocks, 2000)):
            update_stocks(some_stock, campaign_dbs_id, market_token)
        # Поменять цены DBS
        upload_prices(watch_remnants, campaign_dbs_id, market_token)
    except requests.exceptions.ReadTimeout:
        print("Превышено время ожидания...")
    except requests.exceptions.ConnectionError as error:
        print(error, "Ошибка соединения")
    except Exception as error:
        print(error, "ERROR_2")


if __name__ == "__main__":
    main()
