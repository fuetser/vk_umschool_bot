import datetime
import json
import random
import requests
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard
from bs4 import BeautifulSoup
from db import User, Session


class App():
    def __init__(self, token: str, group_id: int):
        self.token = token
        self.group_id = group_id

        self.vk_session = vk_api.VkApi(token=self.token)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, self.group_id)

        self.state = "start"
        self.city = None
        self.session = Session()
        self.fill_cities_dict()

    def fill_cities_dict(self):
        # метод для получения словаря с русскими и английскими названиями городов для афишы
        resp = requests.get("https://gorodzovet.ru/?cities=all")
        soup = BeautifulSoup(resp.text, "lxml")
        cities = soup.findAll("a", class_="city_item")
        self.cities_names = {}
        for city in cities:
            self.cities_names[city.text.strip().lower()] = city["href"].replace("/", "")

    def insert_into_db(self, user_id: int, city: str):
        # метод для создания нового пользователя в базе данных
        self.session.add(User(user_id, city))
        self.session.commit()

    def get_from_db(self, user_id: int):
        # метод для поиска пользователя в базе данных по id вконтакте
        return self.session.query(User).where(User.user_id == user_id).first()

    def update_city(self, user_id: int, new_city: str):
        # метод для изменения города у пользователя
        user = self.get_from_db(user_id)
        user.city = new_city
        self.session.add(user)
        self.session.commit()

    def send_message(self, user_id, message, keyboard=None):
        # метод для отправки сообщения пользователю
        keyboard = self.get_keyboard() if keyboard is None else keyboard
        self.vk.messages.send(
            user_id=user_id,
            message=message,
            keyboard=keyboard,
            random_id=random.randint(0, 2**64)
        )

    def get_city_from_user(self, user_id: int):
        # метод для получения города со страницы пользователя
        user_data = self.vk.users.get(user_ids=user_id, fields="city")
        if not user_data:
            return
        if user_data[0].get("can_access_closed", False):
            if (city := user_data[0].get("city")) is not None:
                return city['title']

    def get_keyboard(self, buttons: list[str] = None, colors: list[str] = None):
        # метод для создания клавиатуры по списку кнопок
        keyboard = VkKeyboard()
        if not buttons:
            return keyboard.get_empty_keyboard()
        for i in range(len(buttons)):
            if i > 0 and i % 3 == 0:
                keyboard.add_line()
            color = "primary" if i == 0 else "secondary"
            if colors:
                color = colors[i]
            keyboard.add_button(buttons[i], color)
        return keyboard.get_keyboard()

    def get_main_keyboard(self):
        return self.get_keyboard(("Погода", "Пробки", "Афиша", "Валюта", "Изменить город"))

    def get_start_keyboard(self):
        return self.get_keyboard(("Начать", ))

    def get_confirm_keyboard(self):
        return self.get_keyboard(("Да", "Нет"), ("positive", "negative"))

    def get_days_keyboard(self):
        return self.get_keyboard(("Сегодня", "Завтра", "Назад"))

    def confirm_city(self, user_id: int, message_text: str):
        # метод для обработки процесса подтверждения города пользователя
        if message_text == "нет":
            self.send_message(user_id, "Пожалуйста, укажите ваш город")
            self.state = "choose_city"
        elif message_text == "да":
            self.insert_into_db(user_id, self.city)
            self.send_message(user_id, "Город успешно зарегистрирован")
            self.switch_to_main_state(user_id)
        else:
            keyboard = self.get_confirm_keyboard()
            self.send_message(user_id, f"Ваш город - {self.city}, верно?", keyboard)

    def choose_city(self, user_id: int, message_text: str):
        # метод для обработки процесса выбора города пользователем
        if self.get_from_db(user_id):
            self.update_city(user_id, message_text)
        else:
            self.insert_into_db(user_id, message_text.strip())
            self.city = message_text.strip()
        self.send_message(user_id, "Город успешно зарегистрирован")
        self.switch_to_main_state(user_id)

    def switch_to_main_state(self, user_id: int):
        # метод для отправки пользователю главной клавиатуры
        keyboard = self.get_main_keyboard()
        self.send_message(user_id, "Выберите действие:", keyboard)
        self.state = "main"

    def get_json(self, url: str):
        # метод для выполнения get запроса и предоставления ответа в формате json
        resp = requests.get(url)
        if resp.ok:
            return json.loads(resp.text)

    def get_city_coords(self, city: str, key: str):
        # метод для получения координат города по названию
        url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={key}"
        json_data = self.get_json(url)
        if json_data:
            lat = json_data[0].get("lat", 0)
            lon = json_data[0].get("lon", 0)
            return lat, lon

    def get_weather(self, user_id: int, message_text: str):
        # метод для получения погоды в городе пользователя
        key = ""
        city = self.get_from_db(user_id).city
        if (coords := self.get_city_coords(city, key)) is not None:
            lat, lon = coords
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={key}&units=metric&lang=ru"
            json_data = self.get_json(url)
            if json_data is not None:
                if message_text == "завтра":
                    weather_by_hours = []
                    tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
                    tomorrow = tomorrow.strftime("%Y-%m-%d")
                    for record in json_data["list"]:
                        if record["dt_txt"].split()[0] == tomorrow:
                            weather_by_hours.append(record)
                    json_data = weather_by_hours[len(weather_by_hours) // 2]
                else:
                    json_data = json_data["list"][0]
                return json_data

    def handle_weather(self, user_id: int, message_text: str):
        # метод для обработки процесса выбора дня для отображения погоды
        if message_text in ("сегодня", "завтра"):
            json_data = self.get_weather(user_id, message_text)
            if json_data is not None:
                self.send_message(
                    user_id,
                    f"{json_data['weather'][0]['description'].capitalize()}\n"
                    f"Темература {json_data['main']['temp']} C\n"
                    f"Ощущается как {json_data['main']['feels_like']} C\n"
                    f"Влажность {json_data['main']['humidity']}%\n"
                    f"Скорость ветра {json_data['wind']['speed']} м/с"
                )
            else:
                self.send_message(user_id, "Что-то пошло не так...")
            self.switch_to_main_state(user_id)
        else:
            keyboard = self.get_days_keyboard()
            self.send_message(user_id, "Выберите день:", keyboard)

    def handle_currency(self, user_id: int):
        # метод для получения курса валют
        key = ""
        url = f"https://api.freecurrencyapi.com/v1/latest?apikey={key}&base_currency=RUB&currencies=USD,EUR,GBP,JPY,CNY"
        json_data = self.get_json(url)
        if json_data is not None:
            json_data = json_data["data"]
            self.send_message(
                user_id,
                "Курс валют в рублях:\n"
                f"Доллар США {1 / json_data['USD']:.02f}\n"
                f"Евро {1 / json_data['EUR']:.02f}\n"
                f"Британский фунт {1 / json_data['GBP']:.02f}\n"
                f"Японская йена {1 / json_data['JPY']:.02f}\n"
                f"Китайский юань {1 / json_data['CNY']:.02f}\n"
            )
        else:
            self.send_message(user_id, "Что-то пошло не так...")
        self.switch_to_main_state(user_id)

    def get_jams_level(self, lat: float, lon: float):
        # метод для получения уровня пробок
        key = ""
        url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point={lat},{lon}&key={key}"
        json_data = self.get_json(url)
        if json_data is not None:
            current_speed = json_data["flowSegmentData"]["currentSpeed"]
            free_speed = json_data["flowSegmentData"]["freeFlowSpeed"]
            return max(round((1 - current_speed / free_speed) * 10), 1)
        return 1

    def handle_traffic_jams(self, user_id: int):
        # метод для обрабоки сообщения с запросом уровня пробок
        key = ""
        city = self.get_from_db(user_id).city
        if (coords := self.get_city_coords(city, key)) is not None:
            lat, lon = coords
            jams_level = self.get_jams_level(lat, lon)
            self.send_message(user_id, f"Текущий уровень пробок: {jams_level}")
        else:
            self.send_message(user_id, "Что-то пошло не так...")
        self.switch_to_main_state(user_id)

    def get_events(self, city: str, message_text: str):
        # метод для получения списка мероприятий в городе пользователя
        date = datetime.datetime.now()
        if message_text == "завтра":
            date += datetime.timedelta(days=1)
        date = date.strftime("%Y-%m-%d")
        base_url = "https://gorodzovet.ru"
        url = f"{base_url}/{self.cities_names[city]}/day{date}"
        resp = requests.get(url)
        soup = BeautifulSoup(resp.text, "lxml")
        events = []
        for div in soup.find("div", class_="eventsWrapper").findAll("div", class_="event-block"):
            link = div.find("a", class_="event-link")
            title = link.find("h3").text.strip()
            price = link.find("b")
            price = price.text.strip() + " p" if price else "бесплатно"
            events.append((title, price, base_url + link["href"]))
        return events[:5]

    def handle_events(self, user_id: str, message_text: str):
        # метод для обработки процесса выбора даты для отображения мероприятий
        if message_text in ("сегодня", "завтра"):
            city = self.get_from_db(user_id).city.lower()
            if city in self.cities_names:
                events = self.get_events(city, message_text)
                rows = []
                for title, price, link in events:
                    rows.append(f"{title} - {price} ({link})")
                self.send_message(
                    user_id,
                    f"Топ мероприятий в городе {city.capitalize()} {message_text}:\n" + "\n".join(rows)
                )
            else:
                self.send_message(user_id, "К сожалению, для этого города события недоступны")
            self.switch_to_main_state(user_id)
        else:
            keyboard = self.get_days_keyboard()
            self.send_message(user_id, "Выберите день:", keyboard)

    def handle_command(self, user_id: int, message_text: str):
        # метод для обработки команд с клавиатуры
        if message_text == "погода":
            keyboard = self.get_days_keyboard()
            self.send_message(user_id, "Выберите день:", keyboard)
            self.state = "weather"
        elif message_text == "пробки":
            self.handle_traffic_jams(user_id)
        elif message_text == "афиша":
            keyboard = self.get_days_keyboard()
            self.send_message(user_id, "Выберите день:", keyboard)
            self.state = "events"
        elif message_text == "валюта":
            self.handle_currency(user_id)
        elif message_text == "изменить город":
            keyboard = self.get_keyboard(("Назад", ), ("negative", ))
            self.send_message(user_id, "Пожалуйста, укажите ваш город", keyboard)
            self.state = "choose_city"
        else:
            self.send_message(user_id, "Пожалуйста, используйте команды с клавиатуры")
            self.switch_to_main_state(user_id)

    def handle_first_message(self, user_id: int):
        # метод для обработки первого сообщения от пользователя
        if not self.get_from_db(user_id):
            city = self.get_city_from_user(user_id)
            if city is not None:
                keyboard = self.get_confirm_keyboard()
                self.send_message(user_id, f"Ваш город - {city}, верно?", keyboard)
                self.state = "confirm_city"
                self.city = city
            else:
                keyboard = self.get_keyboard(("Назад",), ("negative",))
                self.send_message(user_id, "Пожалуйста, укажите ваш город", keyboard)
                self.state = "choose_city"
        else:
            self.switch_to_main_state(user_id)

    def handle_message(self, event: vk_api.bot_longpoll.VkBotMessageEvent):
        # метод для обработки сообщений от пользователя
        user_id = event.obj.message['from_id']
        message_text = event.message.get("text", "").strip().lower()
        if self.state == "start":
            if message_text == "начать":
                self.handle_first_message(user_id)
            else:
                self.send_message(
                    user_id,
                    'Напишите "Начать" для начала работы',
                    self.get_start_keyboard()
                )
        elif message_text == "назад":
            self.switch_to_main_state(user_id)
        elif self.state == "confirm_city":
            self.confirm_city(user_id, message_text)
        elif self.state == "choose_city":
            self.choose_city(user_id, message_text)
        elif self.state == "main":
            self.handle_command(user_id, message_text)
        elif self.state == "weather":
            self.handle_weather(user_id, message_text)
        elif self.state == "events":
            self.handle_events(user_id, message_text)

    def run(self):
        # метод для запуска бота
        for event in self.longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                self.handle_message(event)
            elif event.obj.message is not None:
                user_id = event.obj.message['from_id']
                self.send_message(user_id, "Пожалуйста, используйте команды с клавиатуры")
                self.switch_to_main_state(user_id)


if __name__ == '__main__':
    app = App(
        token="",
        group_id="",
    )
    app.run()
