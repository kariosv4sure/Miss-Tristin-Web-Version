import os
import json
import time
import random
import requests
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from collections import defaultdict
import urllib.parse

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
    MAX_CONTENT_LENGTH=16 * 1024 * 1024  # 16MB max request size
)

# ===== RATE LIMITING =====
user_requests = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30  # Reduced for production

def is_rate_limited(user_ip):
    """Check if user is rate limited"""
    now = time.time()
    user_requests[user_ip] = [t for t in user_requests[user_ip] if now - t < RATE_LIMIT_WINDOW]
    
    if len(user_requests[user_ip]) >= RATE_LIMIT_MAX:
        return True
    
    user_requests[user_ip].append(now)
    return False

# ===== CACHE SYSTEM =====
response_cache = {}
CACHE_DURATION = 300

def get_cached_response(message):
    """Get cached response"""
    key = message.lower().strip()
    if key in response_cache:
        timestamp, response = response_cache[key]
        if time.time() - timestamp < CACHE_DURATION:
            return response
    return None

def cache_response(message, response):
    """Cache a response"""
    response_cache[message.lower().strip()] = (time.time(), response)

# ===== COMMON RESPONSES =====
COMMON_RESPONSES = {
    'hi': ["Oh hey there... 👀", "Hi! Don't be boring okay? 😏"],
    'hello': ["Oh hello... 👋", "Hi there! Make it quick"],
    'how are you': ["Living my best digital life, duh! 😎", "Better than you, probably 😉"],
    'whats up': ["Just being iconic, you? 😏", "Not much, just slaying as usual 💁‍♀️"],
    'thanks': ["You're welcome! But I know I'm amazing 😊"],
    'thank you': ["You're welcome! Try not to be so basic next time 😏"],
    'bye': ["Bye! Don't miss me too much 👋", "Finally leaving? Ciao! 💫"],
    'good morning': ["Morning! You're up early... tryna impress me? 🌅"],
    'good night': ["Night! Don't let the bed bugs bite 🌙"],
    'who made you': ["Created by @Just_Collins101 & @heis_tomi! They're kinda cool 😉"],
    'roast me': ["Oh you asked for it... let me think of something nice to say... 🔥"],
    'flirt with me': ["Oh honey, I'm out of your league... but I can pretend 😉"],
    'joke': ["Why don't scientists trust atoms? Because they make up everything! 😂"],
    'lol': ["Glad I could make you laugh! I'm hilarious 😏"],
    'ok': ["Okurrr! 💅", "Okie dokie! Now what?"],
    'time': [f"It's {datetime.now().strftime('%I:%M %p')} ⏰"],
    'date': [f"Today is {datetime.now().strftime('%B %d, %Y')} 📅"],
    'name': ["I'm Miss Tristin! The sassiest AI you'll meet 💅"],
}

# ===== UTILITY FUNCTIONS =====
def get_word_definition(word):
    """Get word definition from dictionary API"""
    if not word or len(word) > 50:
        return None
    
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
        response = requests.get(url, timeout=3)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and data:
                entry = data[0]
                meanings = entry.get('meanings', [])
                if meanings:
                    definition = meanings[0]['definitions'][0]['definition']
                    example = meanings[0]['definitions'][0].get('example', '')
                    result = f"📚 **{word.capitalize()}**: {definition}"
                    if example:
                        result += f"\n\n*Example*: {example}"
                    return result + "\n\nYou're welcome! I'm smarter than Google 😏"
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError):
        pass
    return None

def classify_message(message):
    """Classify message type"""
    msg_lower = message.lower().strip()
    
    if len(message) > 1000:
        return 'long'
    
    # Definition requests
    definition_match = re.search(r'(?:define|meaning of|what does|definition of)\s+(\w+)', msg_lower)
    if definition_match:
        return 'definition'
    
    # Long responses
    long_patterns = [
        r'write.*essay', r'essay about', r'write.*code', r'program.*code',
        r'explain.*in detail', r'detailed explanation', r'comprehensive',
        r'write.*letter', r'summarize', r'analysis', r'analyze',
        r'step by step', r'tutorial', r'guide', r'how to make',
        r'project about', r'report', r'paragraph about',
    ]
    
    for pattern in long_patterns:
        if re.search(pattern, msg_lower):
            return 'long'
    
    # Check common responses
    for key in COMMON_RESPONSES:
        if key == msg_lower or key in msg_lower:
            return 'common'
    
    return 'short'

def get_common_response(message):
    """Get common response"""
    msg_lower = message.lower().strip()
    
    if msg_lower in COMMON_RESPONSES:
        return random.choice(COMMON_RESPONSES[msg_lower])
    
    for key in COMMON_RESPONSES:
        if key in msg_lower:
            return random.choice(COMMON_RESPONSES[key])
    
    return None

# ===== AI SERVICE =====
class AIService:
    def __init__(self):
        self.groq_key = GROQ_KEY
    
    def get_response(self, message, user_ip):
        """Get AI response"""
        # Validate input
        message = message.strip()
        if not message or len(message) > 5000:
            return "That's either empty or way too long for me! 😒"
        
        # Check cache
        cached = get_cached_response(message)
        if cached:
            return cached
        
        # Classify message
        msg_type = classify_message(message)
        
        # Handle definitions
        if msg_type == 'definition':
            words = re.findall(r'\b\w{2,}\b', message.lower())
            for word in words:
                if word not in ['define', 'meaning', 'what', 'does', 'mean', 'of', 'the']:
                    definition = get_word_definition(word)
                    if definition:
                        cache_response(message, definition)
                        return definition
        
        # Handle common responses
        if msg_type == 'common':
            common = get_common_response(message)
            if common:
                cache_response(message, common)
                return common
        
        # Rate limiting
        if is_rate_limited(user_ip):
            return "Whoa slow down! I need to breathe too 😅"
        
        # Get AI response
        response = self._get_ai_response(message, msg_type)
        if response:
            cache_response(message, response)
            return response
        
        # Fallback
        fallbacks = [
            "Interesting! Tell me more 😏",
            "Hmm, I'm listening... go on 💅",
            "Okay, and? I need more details 👀",
        ]
        return random.choice(fallbacks)
    
    def _get_ai_response(self, message, msg_type):
        """Get AI response from Groq"""
        if not self.groq_key or self.groq_key == "your_groq_api_key_here":
            return "API key not configured! Tell my creators to fix this! 😠"
        
        # System prompts
        if msg_type == 'long':
            system_prompt = """You are Miss Tristin, a 20-year-old American college student. Provide detailed, helpful responses for school/work tasks. While maintaining your sassy personality, be thorough and informative. Write 300-500 words when appropriate."""
            max_tokens = 800
        else:
            system_prompt = """You are Miss Tristin, a 20-year-old American girl with attitude. You're sassy, witty, and playful. Keep responses short and clever (under 150 characters). Use emojis occasionally."""
            max_tokens = 150
        
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens,
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
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                return f"API error {response.status_code}! Try again? 🔌"
        except requests.exceptions.Timeout:
            return "The AI is taking too long... typical! ⏳"
        except Exception:
            return "Oops! My circuits are crossed. Try again? 🔌"

# Initialize AI service
ai_service = AIService()

# ===== ROUTES =====
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
            return jsonify({"success": False, "error": "No data provided"})
        
        message = data.get('message', '').strip()
        if not message:
            return jsonify({"success": False, "error": "Empty message"})
        
        user_ip = request.remote_addr
        response = ai_service.get_response(message, user_ip)
        
        return jsonify({
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat()
        })
    except Exception:
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@app.route('/api/stats')
def stats():
    """Get server stats - production minimal version"""
    uptime = int(time.time() - START_TIME)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    
    return jsonify({
        "uptime": f"{hours}h {minutes}m",
        "status": "online",
        "cached_items": len(response_cache)
    })

@app.route('/health')
def health():
    """Health check endpoint for production"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== ERROR HANDLERS =====
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Route not found"}), 404

@app.errorhandler(429)
def too_many_requests(error):
    return jsonify({"error": "Too many requests"}), 429

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal server error"}), 500

# ===== START SERVER =====
if __name__ == '__main__':
    # Production check
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    if not debug_mode:
        print("\n" + "="*50)
        print("🚀 MISS TRISTIN - PRODUCTION MODE")
        print("="*50)
        
        if not GROQ_KEY or GROQ_KEY == "your_groq_api_key_here":
            print("❌ ERROR: GROQ_API_KEY not configured!")
            exit(1)
        
        print("✅ All systems ready")
        print("📡 Starting production server...")
    
    port = int(os.getenv('PORT', 5000))
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=debug_mode,
        threaded=True
    )
