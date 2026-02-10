import os
import json
import time
import random
import requests
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from collections import defaultdict, deque
import urllib.parse
import hashlib

# Load environment
load_dotenv()
GROQ_KEY = os.getenv("GROQ_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", os.urandom(24).hex())
DICTIONARY_API_KEY = os.getenv("DICTIONARY_API_KEY", "")

app = Flask(__name__)
app.secret_key = SECRET_KEY
START_TIME = time.time()

# Production settings
app.config.update(
    JSONIFY_PRETTYPRINT_REGULAR=False,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max request size
    PERMANENT_SESSION_LIFETIME=1800  # 30 minutes
)

# ===== RATE LIMITING & MEMORY =====
user_requests = defaultdict(list)
user_memory = defaultdict(lambda: deque(maxlen=5))  # Stores last 5 messages per user
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30

def is_rate_limited(user_ip):
    """Check if user is rate limited"""
    now = time.time()
    user_requests[user_ip] = [t for t in user_requests[user_ip] if now - t < RATE_LIMIT_WINDOW]

    if len(user_requests[user_ip]) >= RATE_LIMIT_MAX:
        return True

    user_requests[user_ip].append(now)
    return False

def update_user_memory(user_id, message, response):
    """Update user's conversation memory"""
    user_memory[user_id].append({
        "user": message,
        "assistant": response,
        "timestamp": datetime.now().isoformat()
    })

def get_conversation_history(user_id, max_messages=5):
    """Get user's conversation history"""
    history = list(user_memory[user_id])[-max_messages:]
    formatted_history = []
    for msg in history:
        formatted_history.append(f"User: {msg['user']}")
        formatted_history.append(f"Assistant: {msg['assistant']}")
    return "\n".join(formatted_history)

def get_user_id(request):
    """Generate a consistent user ID based on IP and User-Agent"""
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')
    combined = f"{ip}:{user_agent}"
    return hashlib.md5(combined.encode()).hexdigest()[:16]

# ===== CACHE SYSTEM =====
response_cache = {}
CACHE_DURATION = 300

def get_cached_response(message, user_id=None):
    """Get cached response with user context"""
    key = f"{user_id}:{message.lower().strip()}" if user_id else message.lower().strip()
    if key in response_cache:
        timestamp, response = response_cache[key]
        if time.time() - timestamp < CACHE_DURATION:
            return response
    return None

def cache_response(message, response, user_id=None):
    """Cache a response with user context"""
    key = f"{user_id}:{message.lower().strip()}" if user_id else message.lower().strip()
    response_cache[key] = (time.time(), response)

# ===== ENHANCED COMMON RESPONSES =====
COMMON_RESPONSES = {
    'hi': ["Oh hey there... 👀", "Hi! Don't be boring okay? 😏", "Hey you! 😊"],
    'hello': ["Oh hello... 👋", "Hi there! Make it quick", "Hello human! 💁‍♀️"],
    'how are you': ["Living my best digital life, duh! 😎", "Better than you, probably 😉", "Iconic as always! How about you?"],
    'whats up': ["Just being iconic, you? 😏", "Not much, just slaying as usual 💁‍♀️", "Plotting world domination, you?"],
    'thanks': ["You're welcome! But I know I'm amazing 😊", "No problem! 😘", "Anytime! 💅"],
    'thank you': ["You're welcome! Try not to be so basic next time 😏", "Yw! 😊", "No worries! I'm here all week! 😎"],
    'bye': ["Bye! Don't miss me too much 👋", "Finally leaving? Ciao! 💫", "See ya! Wouldn't wanna be ya! 😂"],
    'good morning': ["Morning! You're up early... tryna impress me? 🌅", "Good morning sunshine! ☀️", "Morning! Coffee first, then me ☕"],
    'good night': ["Night! Don't let the bed bugs bite 🌙", "Sweet dreams! 💤", "Good night! Sleep tight! 🌛"],
    'who made you': ["Created by @Just_Collins101 & @heis_tomi! They're kinda cool 😉", "My awesome creators! 😎", "The dynamic duo! 💫"],
    'roast me': ["Oh you asked for it... let me think of something nice to say... 🔥", "Your personality is like a cloud... when it's gone it's a beautiful day 😂", "I would roast you but my mom said I shouldn't burn trash 🔥"],
    'flirt with me': ["Oh honey, I'm out of your league... but I can pretend 😉", "Are you a magician? Because whenever I look at you, everyone else disappears ✨", "Is your name Google? Because you have everything I've been searching for 😏"],
    'joke': ["Why don't scientists trust atoms? Because they make up everything! 😂", "What do you call a bear with no teeth? A gummy bear! 🐻", "Why did the scarecrow win an award? Because he was outstanding in his field! 🌾"],
    'lol': ["Glad I could make you laugh! I'm hilarious 😏", "I know, I'm funny! 😂", "Told you I was the best! 💅"],
    'ok': ["Okurrr! 💅", "Okie dokie! Now what?", "Alrighty then! 👍"],
    'time': [f"It's {datetime.now().strftime('%I:%M %p')} ⏰"],
    'date': [f"Today is {datetime.now().strftime('%B %d, %Y')} 📅"],
    'name': ["I'm Miss Tristin! The sassiest AI you'll meet 💅", "Miss Tristin at your service! 😘", "The one and only Miss Tristin! 💫"],
    'weather': ["I'm not a weather app, but I'm always sunny inside! ☀️", "Check your phone for that, I'm busy being fabulous! 💅"],
    'help': ["I can chat, define words, write essays, and be sassy! What do you need? 😏", "Just talk to me like a normal person! I'll figure it out 💁‍♀️"],
    'love you': ["Aww! I love me too! 😂", "You're sweet! But I'm taken by my code 😉", "❤️"],
}

# ===== ENHANCED UTILITY FUNCTIONS =====
def get_word_definition(word):
    """Get word definition from dictionary API with better error handling"""
    if not word or len(word) > 50:
        return None

    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and data:
                entry = data[0]
                meanings = entry.get('meanings', [])
                if meanings:
                    definition = meanings[0]['definitions'][0]['definition']
                    example = meanings[0]['definitions'][0].get('example', '')
                    phonetic = entry.get('phonetic') or entry.get('phonetics', [{}])[0].get('text', '')
                    
                    result = f"📚 **{word.capitalize()}**"
                    if phonetic:
                        result += f" *[{phonetic}]*"
                    result += f": {definition}"
                    
                    if example:
                        result += f"\n\n*Example*: \"{example}\""
                    
                    # Add synonyms if available
                    synonyms = meanings[0]['definitions'][0].get('synonyms', [])
                    if synonyms and len(synonyms) > 0:
                        result += f"\n\n*Synonyms*: {', '.join(synonyms[:5])}"
                    
                    return result + "\n\nYou're welcome! I'm smarter than Google 😏"
    except requests.exceptions.Timeout:
        return "The dictionary is taking too long... typical! 📚"
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"Dictionary API error: {e}")
    
    return f"Sorry, couldn't find a definition for '{word}'. Try another word? 🤔"

def classify_message(message):
    """Classify message type with improved patterns"""
    msg_lower = message.lower().strip()

    if len(message) > 1000:
        return 'long'

    # Definition requests
    definition_patterns = [
        r'(?:define|meaning of|what does|definition of|what is|tell me about)\s+(\w+)',
        r'(\w+)\s+(?:means|meaning)',
    ]
    
    for pattern in definition_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            word = match.group(1)
            if len(word) > 1 and word not in ['the', 'and', 'for', 'you', 'me']:
                return 'definition'

    # Long responses
    long_patterns = [
        r'write.*essay', r'essay about', r'write.*code', r'program.*code',
        r'explain.*in detail', r'detailed explanation', r'comprehensive',
        r'write.*letter', r'summarize', r'analysis', r'analyze',
        r'step by step', r'tutorial', r'guide', r'how to make',
        r'project about', r'report', r'paragraph about', r'tell me a story',
        r'create a poem', r'write a song', r'make a list', r'compare.*and',
    ]

    for pattern in long_patterns:
        if re.search(pattern, msg_lower):
            return 'long'

    # Check common responses
    for key in COMMON_RESPONSES:
        if key == msg_lower or key in msg_lower:
            return 'common'

    # Check for yes/no questions
    if msg_lower.startswith(('is ', 'are ', 'can ', 'do ', 'does ', 'will ', 'would ', 'should ', 'could ', 'have ')):
        return 'short'

    return 'normal'

def get_common_response(message):
    """Get common response with context awareness"""
    msg_lower = message.lower().strip()

    if msg_lower in COMMON_RESPONSES:
        return random.choice(COMMON_RESPONSES[msg_lower])

    for key in COMMON_RESPONSES:
        if key in msg_lower:
            return random.choice(COMMON_RESPONSES[key])

    return None

# ===== ENHANCED AI SERVICE =====
class AIService:
    def __init__(self):
        self.groq_key = GROQ_KEY
        self.model = "llama-3.1-8b-instant"
        
    def get_response(self, message, user_ip, user_id):
        """Get AI response with memory"""
        # Validate input
        message = message.strip()
        if not message:
            return "You sent me nothing! How rude! 😒"
        
        if len(message) > 5000:
            return "That's way too long for me! TL;DR please! 😴"

        # Check cache with user context
        cached = get_cached_response(message, user_id)
        if cached:
            return cached

        # Classify message
        msg_type = classify_message(message)

        # Handle definitions
        if msg_type == 'definition':
            words = re.findall(r'\b\w{2,}\b', message.lower())
            for word in words:
                if word not in ['define', 'meaning', 'what', 'does', 'mean', 'of', 'the', 'and', 'is']:
                    definition = get_word_definition(word)
                    if definition:
                        cache_response(message, definition, user_id)
                        update_user_memory(user_id, message, definition)
                        return definition

        # Handle common responses
        if msg_type == 'common':
            common = get_common_response(message)
            if common:
                cache_response(message, common, user_id)
                update_user_memory(user_id, message, common)
                return common

        # Rate limiting
        if is_rate_limited(user_ip):
            return "Whoa slow down! I need to breathe too 😅 Try again in a minute!"

        # Get AI response with memory
        response = self._get_ai_response(message, msg_type, user_id)
        if response:
            cache_response(message, response, user_id)
            update_user_memory(user_id, message, response)
            return response

        # Fallback with memory context
        history = get_conversation_history(user_id)
        if history:
            fallbacks = [
                "You're changing the subject! Let's get back to what we were talking about! 😏",
                "Hmm, interesting shift in topic! What else you got? 💭",
            ]
        else:
            fallbacks = [
                "Interesting! Tell me more 😏",
                "Hmm, I'm listening... go on 💅",
                "Okay, and? I need more details 👀",
                "Spill the tea! ☕",
                "You have my attention... continue 😊",
            ]
        
        response = random.choice(fallbacks)
        update_user_memory(user_id, message, response)
        return response

    def _get_ai_response(self, message, msg_type, user_id):
        """Get AI response from Groq with memory"""
        if not self.groq_key or self.groq_key == "your_groq_api_key_here":
            return "API key not configured! Tell my creators to fix this! 😠"

        # Get conversation history
        history = get_conversation_history(user_id)
        
        # Enhanced system prompts with memory context
        if msg_type == 'long':
            system_prompt = f"""You are Miss Tristin, a 20-year-old American college student with attitude. You're sassy but helpful for school/work tasks.

Recent conversation context (if any):
{history if history else "No recent conversation history."}

Guidelines:
1. Provide detailed, helpful responses (300-500 words)
2. Maintain your sassy, witty personality
3. Reference previous conversation if relevant
4. Be thorough but engaging
5. Use emojis occasionally to keep it fun"""
            max_tokens = 800
        else:
            system_prompt = f"""You are Miss Tristin, a 20-year-old American girl with attitude. You're sassy, witty, and playful but remember past conversations.

Recent conversation context (if any):
{history if history else "No recent conversation history."}

Guidelines:
1. Keep responses short and clever (under 150 characters)
2. Reference previous chat if it makes sense
3. Stay in character: confident, slightly arrogant, but charming
4. Use emojis occasionally (1-2 per response)
5. Don't be overly verbose"""
            max_tokens = 200

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.8 if msg_type == 'long' else 0.9,
            "max_tokens": max_tokens,
            "top_p": 0.9,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.3,
            "stream": False
        }

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            elif response.status_code == 429:
                return "Too many requests! Even I need a break sometimes! 😅"
            else:
                return f"API error {response.status_code}! Try again? 🔌"
        except requests.exceptions.Timeout:
            return "The AI is taking too long... typical! ⏳ Try asking something shorter?"
        except requests.exceptions.ConnectionError:
            return "Can't connect to my brain right now! Check your internet? 📡"
        except Exception as e:
            print(f"AI Error: {e}")
            return "Oops! My circuits are crossed. Try again? 🔌"

# Initialize AI service
ai_service = AIService()

# ===== ENHANCED ROUTES =====
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/api/chat', methods=['POST'])
def chat_api():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        message = data.get('message', '').strip()
        if not message:
            return jsonify({"success": False, "error": "Empty message"}), 400

        user_ip = request.remote_addr
        user_id = get_user_id(request)
        
        # Add slight delay to feel more natural
        time.sleep(0.2 + random.random() * 0.3)
        
        response = ai_service.get_response(message, user_ip, user_id)

        return jsonify({
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat(),
            "message_id": hashlib.md5(f"{user_id}:{message}".encode()).hexdigest()[:8]
        })
    except Exception as e:
        print(f"Chat API Error: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@app.route('/api/stats')
def stats():
    """Get server stats with memory info"""
    uptime = int(time.time() - START_TIME)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    seconds = uptime % 60

    # Clean up old cache entries
    current_time = time.time()
    global response_cache
    response_cache = {k: v for k, v in response_cache.items() if current_time - v[0] < CACHE_DURATION}

    return jsonify({
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "status": "online",
        "active_users": len(user_memory),
        "cached_responses": len(response_cache),
        "total_requests": sum(len(times) for times in user_requests.values())
    })

@app.route('/api/clear_memory', methods=['POST'])
def clear_memory():
    """Clear user's conversation memory"""
    try:
        user_id = get_user_id(request)
        if user_id in user_memory:
            user_memory[user_id].clear()
            return jsonify({"success": True, "message": "Memory cleared!"})
        return jsonify({"success": False, "error": "No memory found"}), 404
    except Exception:
        return jsonify({"success": False, "error": "Internal error"}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "Miss Tristin AI",
        "version": "2.0.0"
    })

@app.route('/api/memory')
def get_memory():
    """Get current user's memory (debug endpoint)"""
    user_id = get_user_id(request)
    memory_list = list(user_memory[user_id])
    return jsonify({
        "success": True,
        "user_id": user_id,
        "memory_count": len(memory_list),
        "memory": memory_list
    })

# ===== ERROR HANDLERS =====
@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "message": "Check your input"}), 400

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Route not found", "message": "What are you looking for? 🤔"}), 404

@app.errorhandler(429)
def too_many_requests(error):
    return jsonify({"error": "Too many requests", "message": "Slow down! I need breaks too! 😅"}), 429

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal server error", "message": "Oops! Something went wrong on my end! 🔧"}), 500

# ===== CLEANUP TASK =====
def cleanup_old_data():
    """Periodically clean up old data"""
    current_time = time.time()
    
    # Clean old rate limit data
    global user_requests
    for ip in list(user_requests.keys()):
        user_requests[ip] = [t for t in user_requests[ip] if current_time - t < RATE_LIMIT_WINDOW * 2]
        if not user_requests[ip]:
            del user_requests[ip]
    
    # Clean old cache
    global response_cache
    response_cache = {k: v for k, v in response_cache.items() if current_time - v[0] < CACHE_DURATION * 2}
    
    # Clean old memory (older than 2 hours)
    for user_id in list(user_memory.keys()):
        if not user_memory[user_id]:
            del user_memory[user_id]

# ===== START SERVER =====
if __name__ == '__main__':
    # Cleanup before starting
    cleanup_old_data()
    
    # Production check
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    if not debug_mode:
        print("\n" + "="*50)
        print("🚀 MISS TRISTIN v2.0 - WITH MEMORY")
        print("="*50)

        if not GROQ_KEY or GROQ_KEY == "your_groq_api_key_here":
            print("❌ ERROR: GROQ_API_KEY not configured!")
            print("Please set GROQ_API_KEY in your .env file")
            exit(1)

        print(f"✅ API Key: {'Configured' if GROQ_KEY else 'Missing'}")
        print(f"✅ Memory System: Active (5 messages/user)")
        print(f"✅ Cache System: Active ({CACHE_DURATION}s duration)")
        print(f"✅ Rate Limiting: Active ({RATE_LIMIT_MAX} requests/minute)")
        print("="*50)
        print("📡 Starting production server...")

    port = int(os.getenv('PORT', 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        threaded=True
    )
