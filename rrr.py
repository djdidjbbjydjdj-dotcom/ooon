import asyncio
from telethon.tl.types import Channel
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import PhoneCodeInvalidError, PhoneNumberInvalidError, SessionPasswordNeededError, ChatAdminRequiredError, ChannelPrivateError, UserBannedInChannelError, FloodWaitError
from telethon.sessions import StringSession
from datetime import datetime
import os
import motor.motor_asyncio
import certifi

# --- إعدادات البوت والـ API ---
api_id = 28557217
api_hash = "22fb694b8c569117cc056073fc444597"
bot_token = "6872922603:AAEckw1ILOGNhq9fYQB8L-bK_DAHdSNCue0"
owner_id = 6646631745

# --- إعدادات MongoDB (تم دمج بيانات الاعتماد) ---
# اسم المستخدم: djdidjbbjydjdj_db_user
# كلمة المرور: d1JifOpzMkiL6Mkf

MONGO_URL = "mongodb+srv://djdidjbbjydjdj_db_user:d1JifOpzMkiL6Mkf@cluster0.gm4nvdj.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# --- [تعديل جذري] لضمان الاتصال الآمن والموثوق على Heroku ---
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
    MONGO_URL,
    # استخدم خيار tlsCAFile مع certifi للتحقق من الشهادة (الطريقة الأفضل)
    tlsCAFile=certifi.where(),
    # إضافة خيارات تجعل الاتصال أكثر تسامحاً مع بيئات النشر
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=20000,
    socketTimeoutMS=20000,
)

db = mongo_client["TelethonBotDB"]
users_collection = db["users"]
settings_collection = db["settings"]

bot = TelegramClient("bot", api_id, api_hash).start(bot_token=bot_token)

# --- متغيرات الذاكرة المؤقتة (Cache) ---
users = {}
vip_users = []
added_channels = []

# --- دوال التعامل مع قاعدة البيانات ---

async def load_data_from_db():
    """تحميل البيانات من القاعدة إلى الذاكرة عند التشغيل"""
    global users, vip_users, added_channels
    
    print("جاري الاتصال بـ MongoDB...")
    
    try:
        # فحص الاتصال أولاً - سيقوم بمحاولة الاتصال بالخادم
        await mongo_client.admin.command('ping')
        print("تم الاتصال بقاعدة البيانات بنجاح!")
        
        # تحميل المستخدمين
        users = {}
        async for user in users_collection.find():
            user_id = str(user["_id"])
            users[user_id] = user
            if "sessions" not in users[user_id]: users[user_id]["sessions"] = []
            if "groups" not in users[user_id]: users[user_id]["groups"] = []
        
        # تحميل الإعدادات العامة
        settings = await settings_collection.find_one({"_id": "global_settings"})
        if settings:
            vip_users = settings.get("vip_users", [])
            added_channels = settings.get("added_channels", [])
        else:
            await settings_collection.insert_one({
                "_id": "global_settings",
                "vip_users": [],
                "added_channels": []
            })
            vip_users = []
            added_channels = []
            
        print(f"تم تحميل {len(users)} مستخدم.")
    except Exception as e:
        # إذا استمر هذا الخطأ، فالمشكلة حتماً في Network Access في موقع MongoDB Atlas
        print(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
        print("🛑 الخطوة الأخيرة: تأكد من تفعيل Network Access: 0.0.0.0/0 في MongoDB Atlas!")

async def save_user(user_id):
    """حفظ بيانات مستخدم محدد في القاعدة"""
    user_id_str = str(user_id)
    if user_id_str in users:
        user_data = users[user_id_str].copy()
        user_data["_id"] = int(user_id)
        try:
            # زيادة مهلة الاختيار في حال كان الخادم بطيئاً في الاستجابة
            await users_collection.replace_one({"_id": int(user_id)}, user_data, upsert=True)
        except Exception as e:
            print(f"Error saving user {user_id}: {e}")

async def save_global_settings():
    """حفظ إعدادات VIP والقنوات"""
    try:
        await settings_collection.update_one(
            {"_id": "global_settings"},
            {"$set": {"vip_users": vip_users, "added_channels": added_channels}},
            upsert=True
        )
    except Exception as e:
        print(f"Error saving settings: {e}")

def is_vip(user_id):
    return user_id == owner_id or user_id in vip_users

# --- القوائم والأزرار ---
home_markup = [
    [Button.inline("- الحسابات -", b"acc_mun")],
    [Button.inline("- إدارة السوبرات -", b"manage_super"), Button.inline("- إعدادات النشر -", b"posting_settings")], 
    [Button.inline("- تحكم المطور -", b"manage_vip")],
]

# --- بدء البوت ---
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    user_id = event.sender_id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        users[user_id_str] = {
            "_id": user_id,
            "sessions": [], 
            "groups": [], 
            "posting": False, 
            "caption_1": "",
            "caption_2": "",
            "caption_3": "", 
            "caption_4": "",
            "waitTime": 60
        }
        await save_user(user_id)

    if added_channels:
        channel = added_channels[0]
        try:
            participants = await bot.get_participants(channel)
            if user_id not in [u.id for u in participants]:
                await event.reply(
                    f"- يجب عليك الاشتراك في القناة التالية لاستخدام البوت:\n{channel}\n"
                    "- بعد الاشتراك، اضغط /start مجددًا.",
                    buttons=[[Button.url("اشترك في القناة", f"https://t.me/{channel.lstrip('@')}")]]
                )
                return
        except ChatAdminRequiredError:
            pass
        except Exception as e:
            print(f"Error checking channel: {e}")

    await event.reply(
        "- مرحبًا بك! يمكنك التحكم في حسابك باستخدام الخيارات التالية:",
        buttons=home_markup
    )

@bot.on(events.CallbackQuery(data=b"home"))
async def back_to_home(event):
    await event.edit(
        "- مرحبًا بك! يمكنك التحكم في حسابك باستخدام الخيارات التالية:",
        buttons=home_markup
    )

@bot.on(events.CallbackQuery(data=b"acc_mun"))
async def acc_mun(event):
    buttons = [
        [Button.inline("اضف حساب", b"register"), Button.inline("حذف حساب", b"delete_account")],
        [Button.inline("عرض الحسابات", b"view_account")],
        [Button.inline("العودة", b"home")]
    ]
    await event.edit("-قائمة الحسابات :", buttons=buttons)
    
@bot.on(events.CallbackQuery(data=b"manage_vip"))
async def manage_vip(event):
    user_id = event.sender_id
    if user_id != owner_id:
        await event.answer("- هذه الميزة متاحة للمالك فقط.", alert=True)
        return
    buttons = [
        [Button.inline("إضافة مستخدم VIP", b"add_vip"), Button.inline("حذف مستخدم VIP", b"remove_vip")],
        [Button.inline("عرض المستخدمين VIP", b"list_vip")],
        [Button.inline("- إضافة قناة الاشتراك -", b"add_subscription_channel"), Button.inline("- عرض الإحصائيات -", b"stats")],
        [Button.inline("العودة", b"home")]
    ]
    await event.edit("-تحكم المطور :", buttons=buttons)

@bot.on(events.CallbackQuery(data=b"add_vip"))
async def add_vip(event):
    user_id = event.sender_id
    if user_id != owner_id: return

    async with bot.conversation(owner_id) as conv:
        await conv.send_message("- أرسل معرف المستخدم الذي تريد إضافته كمستخدم VIP:")
        vip_id = (await conv.get_response(timeout=None)).text.strip()

        try:
            vip_id = int(vip_id)
            if vip_id in vip_users:
                await conv.send_message("- المستخدم موجود بالفعل كمستخدم VIP.")
            else:
                vip_users.append(vip_id)
                await save_global_settings()
                await conv.send_message(f"- تم إضافة المستخدم {vip_id} كمستخدم VIP.")
        except ValueError:
            await conv.send_message("- يرجى إدخال معرف مستخدم صالح (رقم فقط).")

@bot.on(events.CallbackQuery(data=b"remove_vip"))
async def remove_vip(event):
    user_id = event.sender_id
    if user_id != owner_id: return

    async with bot.conversation(owner_id) as conv:
        await conv.send_message("- أرسل معرف المستخدم الذي تريد حذفه من قائمة VIP:")
        vip_id = (await conv.get_response(timeout=None)).text.strip()

        try:
            vip_id = int(vip_id)
            if vip_id in vip_users:
                vip_users.remove(vip_id)
                await save_global_settings()
                await conv.send_message(f"- تم حذف المستخدم {vip_id} من قائمة VIP.")
            else:
                await conv.send_message("- المستخدم غير موجود في قائمة VIP.")
        except ValueError:
            await conv.send_message("- يرجى إدخال معرف مستخدم صالح (رقم فقط).")

@bot.on(events.CallbackQuery(data=b"manage_super"))
async def manage_super(event):
    await event.edit(
        "- إدارة السوبرات:",
        buttons=[
            [Button.inline("إضافة سوبر", b"newSuper"), Button.inline("عرض السوبرات", b"currentSupers")],
            [Button.inline("حذف سوبر", b"deleteSpecificSuper"), Button.inline("حذف جميع السوبرات", b"deleteAllSupers")], 
            [Button.inline("العودة", b"home")]
        ]
    )

@bot.on(events.CallbackQuery(data=b"newSuper"))
async def new_super(event):
    user_id = event.sender_id
    await event.delete()

    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل رابط السوبر لإضافته:")
        super_group_link = (await conv.get_response(timeout=None)).text.strip()

        if not super_group_link:
            await conv.send_message("- يرجى إرسال رابط صالح للقروب.")
            return
        if super_group_link.startswith("https://t.me/+"):
            if not is_vip(user_id):
                await bot.send_message(user_id, "- عذرًا، لا يمكنك إضافة رابط خاص لأنك لست VIP.")
                return

        if "groups" in users[str(user_id)] and super_group_link in users[str(user_id)]["groups"]:
            await conv.send_message("- الرابط تم إضافته بالفعل.")
            return
            
        sessions = users[str(user_id)].get("sessions", [])
        if not sessions:
            await bot.send_message(user_id, "- لا توجد جلسات مسجلة لإضافة السوبر.")
            return
            
        valid_session_found = False
        for session_data in sessions:
            session_string = session_data.get("session")
            if not session_string: continue
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized(): raise Exception("Auth Error")
                try:
                    await client(JoinChannelRequest(super_group_link))
                    if "groups" not in users[str(user_id)]: users[str(user_id)]["groups"] = []
                    users[str(user_id)]["groups"].append(super_group_link)
                    await save_user(user_id)
                    await bot.send_message(user_id, f"- تم إضافة السوبر بنجاح: {super_group_link}")
                    valid_session_found = True
                    break
                except Exception as e:
                    await bot.send_message(user_id, f"- حدث خطأ أثناء الانضمام: {str(e)}")
            except Exception:
                users[str(user_id)]["sessions"] = [s for s in users[str(user_id)]["sessions"] if s["session"] != session_string]
                await save_user(user_id)
            finally:
                await client.disconnect()
        if not valid_session_found:
            await bot.send_message(user_id, "حدث خطأ حاول الانضمام للرابط بشكل يدوي وارجع اضفه")

@bot.on(events.CallbackQuery(data=b"currentSupers"))
async def current_supers(event):
    user_id = event.sender_id
    groups = users[str(user_id)].get("groups", [])
    if not groups:
        await event.answer("- لا توجد سوبرات مضافة.", alert=True)
    else:
        buttons = []
        for group in groups:
            display_text = group if len(group) < 30 else group[:27] + "..."
            buttons.append([Button.inline(display_text, f"delSuper:{groups.index(group)}")])
        buttons.append([Button.inline("العودة", b"home")])
        await event.edit("- السوبرات المضافة:", buttons=buttons)

@bot.on(events.CallbackQuery(data=b"deleteAllSupers"))
async def delete_all_supers(event):
    user_id = event.sender_id
    if "groups" in users[str(user_id)] and users[str(user_id)]["groups"]:
        users[str(user_id)]["groups"] = []
        await save_user(user_id)
        await bot.send_message(user_id, "- تم حذف جميع السوبرات بنجاح.")
    else:
        await bot.send_message(user_id, "- لا توجد سوبرات لحذفها.")

@bot.on(events.CallbackQuery(data=b"add_subscription_channel"))
async def add_subscription_channel(event):
    user_id = event.sender_id
    if user_id != owner_id: return
    
    global added_channels 
    added_channels = []
    async with bot.conversation(owner_id) as conv:
        await conv.send_message("- أرسل معرف القناة التي تريد إضافتها كقناة اشتراك (مثل: @M_D_I):")
        channel_username = (await conv.get_response(timeout=None)).text.strip()
        added_channels.append(channel_username)
        await save_global_settings()
        await conv.send_message(f"- تم تعيين القناة التالية كقناة اشتراك إجباري: {channel_username}")

@bot.on(events.CallbackQuery(data=b"list_vip"))
async def list_vip(event):
    user_id = event.sender_id
    if user_id != owner_id: return
    if not vip_users:
        await event.edit("- لا يوجد مستخدمون VIP حاليًا.", buttons=[[Button.inline("العودة", b"manage_vip")]])
    else:
        vip_list = "\n".join([f"- {vip_id}" for vip_id in vip_users])
        await event.edit(f"- قائمة المستخدمين VIP:\n\n{vip_list}", buttons=[[Button.inline("العودة", b"manage_vip")]])

@bot.on(events.CallbackQuery(data=b"register"))
async def register_account(event):
    user_id = event.sender_id
    await event.delete()
    if str(user_id) not in users:
        users[str(user_id)] = {"_id": user_id, "sessions": [], "groups": [], "posting": False}
    max_accounts = 10 if (user_id == owner_id or user_id in vip_users) else 1
    if len(users[str(user_id)]["sessions"]) >= max_accounts:
        await bot.send_message(user_id, f"- لقد وصلت إلى الحد الأقصى ({max_accounts}).")
        return
            
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل كود الجلسة الخاص بك:")
        try:
            response = await conv.get_response(timeout=60)
            session_string = response.text.strip()
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized(): raise Exception("Auth Error")
                me = await client.get_me()
                full_name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
                await conv.send_message(f"- تم تسجيل الدخول باستخدام الجلسة بنجاح! مرحبًا {full_name} .")
                users[str(user_id)]["sessions"].append({"session": session_string, "username": me.username, "id": me.id})
                await save_user(user_id)
            except Exception:
                await conv.send_message(f"- الجلسة غير صالحة استخرج واحده جديدة وحاول مجدداً")
            finally:
                await client.disconnect()
        except asyncio.TimeoutError:
            await conv.send_message("- لم يتم الرد في الوقت المحدد.")

@bot.on(events.CallbackQuery(data=b"view_account"))
async def view_account(event):
    user_id = event.sender_id
    sessions = users[str(user_id)].get("sessions", [])    
    if not sessions:
        await event.edit("- لا توجد حسابات مسجلة.", buttons=[[Button.inline("تسجيل حساب", b"register")]])
        return
        
    accounts_info = []
    valid_sessions = []
    has_changes = False
    
    for i, session_data in enumerate(sessions):
        session_string = session_data["session"]
        try:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized(): raise Exception("Auth Error")
            me = await client.get_me()
            full_name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
            accounts_info.append(f"**الحساب {i+1}:**\n- **الاسم**: {full_name}\n- **ID**: {me.id}")
            valid_sessions.append(session_data)
        except Exception:
            accounts_info.append(f"**الحساب {i+1}:**\n- الجلسة غير صالحة وتم حذفها")
            has_changes = True
        finally:
            await client.disconnect()
            
    if has_changes:
        users[str(user_id)]["sessions"] = valid_sessions
        await save_user(user_id)

    await event.edit(f"- الحسابات الحالية:\n\n" + "\n\n".join(accounts_info), buttons=[[Button.inline("العودة", b"home")]])

@bot.on(events.CallbackQuery(data=b"posting_settings"))
async def posting_settings(event):
    await event.edit("- إعدادات النشر:", buttons=[
        [Button.inline("تعيين الكليشة", b"newCaption"), Button.inline("الكليشة الثانية", b"newCaption2")],
        [Button.inline("الكليشة الثالثة", b"newCaption3"), Button.inline("الكليشة الرابعة", b"newCaption4")],
        [Button.inline("حذف الكلايش", b"deleteAllCaptions")],
        [Button.inline("بدء النشر", b"startPosting"), Button.inline("إيقاف النشر", b"stopPosting")],
        [Button.inline("تعيين وقت الانتظار", b"waitTime")],
        [Button.inline("العودة", b"home")]
    ])

@bot.on(events.CallbackQuery(data=b"deleteAllCaptions"))
async def delete_all_captions(event):
    user_id = event.sender_id
    for i in range(1, 5): users[str(user_id)][f"caption_{i}"] = ""
    await save_user(user_id)
    await bot.send_message(user_id, "- تم مسح جميع الكلايش بنجاح!")

async def set_caption(event, key, msg):
    user_id = event.sender_id
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message(f"- أرسل {msg}:") 
        val = (await conv.get_response(timeout=None)).text 
        users[str(user_id)][key] = val
        await save_user(user_id)
        await bot.send_message(user_id, f"- تم تحديث {msg} بنجاح!")

@bot.on(events.CallbackQuery(data=b"newCaption"))
async def new_caption(event): await set_caption(event, "caption_1", "الكليشة الجديدة")
@bot.on(events.CallbackQuery(data=b"newCaption2"))
async def new_caption2(event): 
    if not is_vip(event.sender_id): return await bot.send_message(event.sender_id, "للمشتركين VIP فقط")
    await set_caption(event, "caption_2", "الكليشة الثانية")
@bot.on(events.CallbackQuery(data=b"newCaption3"))
async def new_caption3(event):
    if not is_vip(event.sender_id): return await bot.send_message(event.sender_id, "للمشتركين VIP فقط")
    await set_caption(event, "caption_3", "الكليشة الثالثة")
@bot.on(events.CallbackQuery(data=b"newCaption4"))
async def new_caption4(event):
    if not is_vip(event.sender_id): return await bot.send_message(event.sender_id, "للمشتركين VIP فقط")
    await set_caption(event, "caption_4", "الكليشة الرابعة")

@bot.on(events.CallbackQuery(data=b"waitTime"))
async def wait_time(event):
    user_id = event.sender_id
    await event.delete()
    async with bot.conversation(user_id) as conv:
        await conv.send_message("- أرسل مدة الانتظار (بالثواني):")
        try:
            wait_val = int((await conv.get_response(timeout=None)).text)
            if wait_val <= 59: raise ValueError
            users[str(user_id)]["waitTime"] = wait_val
            await save_user(user_id)
            await bot.send_message(user_id, f"- تم تعيين الوقت: {wait_val} ثواني")
        except ValueError:
            await bot.send_message(user_id, "يجب أن تكون القيمة رقم وأكبر من 60.")

@bot.on(events.CallbackQuery(data=b"startPosting"))
async def start_posting(event):
    user_id = event.sender_id
    if str(user_id) not in users: return await event.answer("خطأ بالمستخدم", alert=True)
        
    users[str(user_id)]["posting"] = True
    await save_user(user_id)
    await event.answer("- تم بدء النشر التلقائي!")
    
    captions = [users[str(user_id)].get(f"caption_{i}", "") for i in range(1, 5)]
    captions = [c for c in captions if c]
    groups = users[str(user_id)].get("groups", [])
    sessions = users[str(user_id)].get("sessions", [])

    if not sessions or not groups or not captions:
        users[str(user_id)]["posting"] = False
        await save_user(user_id)
        return await event.answer("- تأكد من إضافة حسابات، سوبرات، وكلايش.", alert=True)

    wait_val = users[str(user_id)].get("waitTime", 60)
    
    async def post_in_group(session_string, group):
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized(): raise Exception("Auth")
            while users[str(user_id)]["posting"]:
                for caption in captions:
                    if not users[str(user_id)]["posting"]: break 
                    try:
                        if group.startswith("https://t.me/"):
                            await client(JoinChannelRequest(group))
                        await client.send_message(group, caption)
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds)
                    except (ChannelPrivateError, UserBannedInChannelError):
                        if group in users[str(user_id)]["groups"]:
                            users[str(user_id)]["groups"].remove(group)
                            await save_user(user_id)
                    except Exception as e:
                        print(f"Error: {e}")
                await asyncio.sleep(wait_val)
        except Exception:
            current = users[str(user_id)]["sessions"]
            users[str(user_id)]["sessions"] = [s for s in current if s["session"] != session_string]
            await save_user(user_id)
        finally:
            await client.disconnect()

    tasks = [post_in_group(s["session"], g) for s in sessions for g in groups]
    asyncio.create_task(asyncio.gather(*tasks))

@bot.on(events.CallbackQuery(data=b"stopPosting"))
async def stop_posting(event):
    user_id = event.sender_id
    users[str(user_id)]["posting"] = False
    await save_user(user_id) 
    await event.answer("- تم إيقاف النشر!")

@bot.on(events.CallbackQuery(data=b"stats"))
async def stats(event):
    if event.sender_id != owner_id: return
    await event.edit(
        f"- المستخدمين: {len(users)}\n"
        f"- السوبرات: {sum(len(u.get('groups', [])) for u in users.values())}\n"
        f"- الحسابات: {sum(len(u.get('sessions', [])) for u in users.values())}",
        buttons=[[Button.inline("العودة", b"home")]]
    )

if __name__ == '__main__':
    bot.loop.run_until_complete(load_data_from_db())
    print("Bot is running...")
    bot.run_until_disconnected()
