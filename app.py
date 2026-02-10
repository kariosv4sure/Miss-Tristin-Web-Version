import os
import json
import time
import random
import requests
import re
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from collections import OrderedDict
import urllib.parse
import uuid
from threading import Lock
import threading
import secrets
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()
GROQ_KEY = os.getenv("GROQ_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
app = Flask(__name__)
app.secret_key = SECRET_KEY
START_TIME = time.time()

# ===== PRODUCTION SETTINGS =====
debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
app.config.update(
    JSONIFY_PRETTYPRINT_REGULAR=False,
    SESSION_COOKIE_SECURE=not debug_mode,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=1800
)

# ===== THREAD-SAFE RATE LIMITING =====
class RateLimiter:
    """Thread-safe rate limiter"""
    def __init__(self, window=60, max_requests=30):
        self.window = window
        self.max_requests = max_requests
        self.requests = {}
        self.lock = Lock()
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()
    
    def is_limited(self, ip):
        with self.lock:
            now = time.time()
            
            # Periodic cleanup
            if now - self.last_cleanup > self.cleanup_interval:
                self._cleanup(now)
                self.last_cleanup = now
            
            if ip not in self.requests:
                self.requests[ip] = []
            
            # Remove old requests
            self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
            
            if len(self.requests[ip]) >= self.max_requests:
                return True
            
            self.requests[ip].append(now)
            return False
    
    def _cleanup(self, current_time):
        """Remove old entries"""
        expired_ips = []
        for ip, timestamps in self.requests.items():
            # Keep only recent timestamps
            self.requests[ip] = [t for t in timestamps if current_time - t < self.window * 2]
            if not self.requests[ip]:
                expired_ips.append(ip)
        
        for ip in expired_ips:
            del self.requests[ip]

rate_limiter = RateLimiter()

# ===== SIZE-LIMITED CACHE SYSTEM =====
class LRUCache:
    """Thread-safe LRU cache with size limit"""
    def __init__(self, maxsize=1000, ttl=300):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl
        self.lock = Lock()
    
    def get(self, key):
        with self.lock:
            if key not in self.cache:
                return None
                
            timestamp, value = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
                
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            return value
    
    def set(self, key, value):
        with self.lock:
            # Check and cleanup if needed
            if len(self.cache) >= self.maxsize:
                # Remove oldest entry
                self.cache.popitem(last=False)
            
            self.cache[key] = (time.time(), value)
    
    def cleanup(self):
        """Remove expired entries"""
        with self.lock:
            current_time = time.time()
            expired_keys = []
            for key, (timestamp, _) in self.cache.items():
                if current_time - timestamp > self.ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
    
    def __len__(self):
        return len(self.cache)

# Initialize caches
response_cache = LRUCache(maxsize=500, ttl=300)
definition_cache = LRUCache(maxsize=200, ttl=3600)

# ===== SESSION-BASED MEMORY =====
def get_user_id():
    """Get or create secure session-based user ID"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
        session.permanent = True
        logger.info(f"New session created: {session['user_id'][:8]}...")
    return session['user_id']

def get_memory_key():
    """Get memory storage key for current user"""
    return f"memory:{get_user_id()}"

def update_user_memory(user_message, ai_response):
    """Update user's conversation memory (max 5 exchanges)"""
    memory_key = get_memory_key()
    memory = session.get(memory_key, [])
    
    # Keep only last 5 exchanges
    memory.append({
        "user": user_message[:500],
        "assistant": ai_response[:500],
        "timestamp": datetime.now().isoformat()
    })
    
    if len(memory) > 5:
        memory = memory[-5:]
    
    session[memory_key] = memory
    return memory

def get_conversation_history():
    """Get formatted conversation history"""
    memory_key = get_memory_key()
    memory = session.get(memory_key, [])
    
    if not memory:
        return ""
    
    formatted = []
    for exchange in memory[-3:]:  # Last 3 exchanges for context
        formatted.append(f"User: {exchange['user']}")
        formatted.append(f"Assistant: {exchange['assistant']}")
    
    return "\n".join(formatted)

# ===== COMMON RESPONSES =====
COMMON_RESPONSES = {
    'hi': ["Oh hey there... 👀", "Hi! Don't be boring okay? 😏"],
    'hello': ["Oh hello... 👋", "Hi there! Make it quick"],
    'how are you': ["Living my best digital life! 😎", "Iconic as always!"],
    'whats up': ["Just being iconic, you? 😏", "Not much, just slaying as usual 💁‍♀️"],
    'thanks': ["You're welcome! 😊", "No problem! 😘"],
    'thank you': ["You're welcome! 😊", "Yw! 💫"],
    'bye': ["Bye! Don't miss me too much 👋", "Ciao! 💫"],
    'good morning': ["Morning! ☀️", "Good morning! ☕"],
    'good night': ["Night! 🌙", "Sweet dreams! 💤"],
    'who made you': ["Created by @Just_Collins101 & @heis_tomi! They're cool 😎"],
    'roast me': ["Oh you asked for it... let me think... 🔥"],
    'joke': ["Why don't scientists trust atoms? Because they make up everything! 😂"],
    'lol': ["Glad I could make you laugh! 😂"],
    'ok': ["Okurrr! 💅", "Okie dokie! 👍"],
    'time': [f"It's {datetime.now().strftime('%I:%M %p')} ⏰"],
    'date': [f"Today is {datetime.now().strftime('%B %d, %Y')} 📅"],
    'name': ["I'm Miss Tristin! The sassiest AI you'll meet 💅"],
    'weather': ["I'm not a weather app, but I'm always sunny inside! ☀️"],
    'help': ["I can chat, define words, write essays! What do you need? 😏"],
}

# ===== UTILITY FUNCTIONS =====
def get_word_definition(word):
    """Get word definition with proper error handling"""
    if not word or len(word) > 50:
        return None
    
    # Check cache first
    cached = definition_cache.get(word.lower())
    if cached:
        return cached
    
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
                    
                    result = f"📚 **{word.capitalize()}**: {definition}"
                    if example:
                        result += f"\n\n*Example*: \"{example}\""
                    
                    # Cache the result
                    definition_cache.set(word.lower(), result)
                    return result
        elif response.status_code == 404:
            return f"Sorry, I couldn't find a definition for '{word}'. Try another word? 🤔"
    except requests.exceptions.Timeout:
        return "The dictionary service is taking too long... ⏳"
    except Exception as e:
        logger.error(f"Dictionary error: {e}")
    
    return None

def extract_definition_word(message):
    """Properly extract word for definition request"""
    patterns = [
        r'(?:define|meaning of|what does|definition of|what is|tell me about)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)',
        r'([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s+(?:means|meaning)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message.lower())
        if match:
            word = match.group(1).strip()
            # Filter out common words
            common_words = {'the', 'and', 'for', 'you', 'me', 'is', 'are', 'of', 'to', 'in'}
            words = word.split()
            # Take the last word if multiple, as it's often the target
            target_word = words[-1] if len(words) > 1 else word
            if len(target_word) > 2 and target_word not in common_words:
                return target_word
    
    return None

def classify_message(message):
    """Classify message type"""
    msg_lower = message.lower().strip()
    
    if len(message) > 1000:
        return 'long'
    
    # Check for definition requests
    if extract_definition_word(message):
        return 'definition'
    
    # Check common responses
    for key in COMMON_RESPONSES:
        if key == msg_lower or f' {key} ' in f' {msg_lower} ':
            return 'common'
    
    # Long content patterns
    long_patterns = [
        r'write.*essay', r'essay about', r'explain.*in detail',
        r'detailed explanation', r'summarize', r'analysis',
        r'step by step', r'tutorial', r'guide', r'how to make',
        r'paragraph about', r'tell me a story', r'create a poem',
        r'compare.*and', r'list of.*', r'pros and cons'
    ]
    
    for pattern in long_patterns:
        if re.search(pattern, msg_lower):
            return 'long'
    
    return 'normal'

def get_common_response(message):
    """Get cached common response"""
    msg_lower = message.lower().strip()
    
    # Exact match
    if msg_lower in COMMON_RESPONSES:
        return random.choice(COMMON_RESPONSES[msg_lower])
    
    # Contains match
    for key, responses in COMMON_RESPONSES.items():
        if key in msg_lower:
            return random.choice(responses)
    
    return None

# ===== PERIODIC CLEANUP =====
def cleanup_task():
    """Background cleanup task"""
    while True:
        time.sleep(300)  # Run every 5 minutes
        try:
            response_cache.cleanup()
            definition_cache.cleanup()
            rate_limiter._cleanup(time.time())
            logger.debug("Cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
cleanup_thread.start()

# ===== AI SERVICE =====
class AIService:
    def __init__(self):
        self.groq_key = GROQ_KEY
        self.model = "llama-3.1-8b-instant"
        
    def get_response(self, message, user_ip):
        """Get AI response with proper memory and caching"""
        message = message.strip()
        if not message:
            return "You sent me nothing! How rude! 😒"
        
        if len(message) > 5000:
            return "That's way too long for me! TL;DR please! 😴"
        
        # Rate limiting
        if rate_limiter.is_limited(user_ip):
            return "Whoa slow down! I need to breathe too 😅 Try again in a minute!"
        
        # Classify message
        msg_type = classify_message(message)
        
        # Handle definitions
        if msg_type == 'definition':
            word = extract_definition_word(message)
            if word:
                definition = get_word_definition(word)
                if definition:
                    update_user_memory(message, definition)
                    return definition
        
        # Handle common responses
        if msg_type == 'common':
            response = get_common_response(message)
            if response:
                update_user_memory(message, response)
                return response
        
        # Get AI response
        response = self._get_ai_response(message, msg_type)
        if response:
            update_user_memory(message, response)
            return response
        
        # Fallback
        fallbacks = [
            "Interesting! Tell me more 😏",
            "Hmm, I'm listening... go on 💅",
            "Okay, and? I need more details 👀",
        ]
        response = random.choice(fallbacks)
        update_user_memory(message, response)
        return response
    
    def _get_ai_response(self, message, msg_type):
        """Get AI response from Groq"""
        if not self.groq_key or self.groq_key == "your_groq_api_key_here":
            return "API key not configured! Tell my creators to fix this! 🔧"
        
        # Get conversation history
        history = get_conversation_history()
        
        # Safe persona
        if msg_type == 'long':
            system_prompt = f"""You are Miss Tristin, a sassy but helpful AI assistant.

Recent conversation context:
{history if history else "No recent conversation."}

Guidelines:
1. Provide detailed, helpful responses (200-400 words)
2. Maintain a witty, engaging personality
3. Reference previous conversation if relevant
4. Be informative but entertaining
5. Use occasional emojis (1-2 max)"""
            max_tokens = 600
            temperature = 0.7
        else:
            system_prompt = f"""You are Miss Tristin, a sassy AI assistant with personality.

Recent conversation context:
{history if history else "No recent conversation."}

Guidelines:
1. Keep responses concise and clever (under 100 words)
2. Stay in character: confident, witty, helpful
3. Use 0-1 emoji per response
4. Be engaging but professional"""
            max_tokens = 150
            temperature = 0.8
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.9,
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
                timeout=20
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            elif response.status_code == 429:
                return "Too many requests! Even I need a break sometimes! 😅"
            else:
                logger.error(f"Groq API error: {response.status_code}")
                return f"API error! Try again? 🔌"
        except requests.exceptions.Timeout:
            return "Taking too long... try a shorter question? ⏳"
        except Exception as e:
            logger.error(f"AI API error: {e}")
            return "Oops! Something went wrong. Try again? 🔌"

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
    """Main chat endpoint"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        message = data.get('message', '').strip()
        if not message:
            return jsonify({"success": False, "error": "Empty message"}), 400
        
        user_ip = request.remote_addr
        
        # Small random delay for natural feel
        delay = 0.1 + random.random() * 0.4
        time.sleep(min(delay, 0.5))
        
        response = ai_service.get_response(message, user_ip)
        
        return jsonify({
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@app.route('/api/stats')
def stats():
    """Get server stats"""
    uptime = int(time.time() - START_TIME)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    
    return jsonify({
        "uptime": f"{hours}h {minutes}m",
        "status": "online",
        "cache_size": len(response_cache),
        "definition_cache_size": len(definition_cache),
        "active_sessions": len(session) if hasattr(session, 'keys') else 0
    })

@app.route('/api/clear_memory', methods=['POST'])
def clear_memory():
    """Clear current user's memory"""
    memory_key = get_memory_key()
    if memory_key in session:
        session.pop(memory_key, None)
    
    return jsonify({"success": True, "message": "Memory cleared!"})

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Miss Tristin AI",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
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
    logger.error(f"Server error: {error}")
    return jsonify({"error": "Internal server error", "message": "Oops! Something went wrong on my end! 🔧"}), 500

# ===== APPLICATION INITIALIZATION =====
@app.before_request
def before_request():
    """Initialize session if needed"""
    if 'initialized' not in session:
        session['initialized'] = True
        get_user_id()  # Ensure user has an ID

# ===== MAIN =====
if __name__ == '__main__':
    # Print startup info
    print("\n" + "="*50)
    print("🚀 MISS TRISTIN AI - STARTING UP")
    print("="*50)
    print(f"📝 Debug mode: {debug_mode}")
    print(f"🔐 Secure cookies: {app.config['SESSION_COOKIE_SECURE']}")
    print(f"💾 Memory system: Active (session-based)")
    print(f"⚡ Rate limiting: Active ({rate_limiter.max_requests} req/min)")
    print(f"🗑️  Cleanup thread: Running")
    print(f"🔑 API Key: {'Configured' if GROQ_KEY and GROQ_KEY != 'your_groq_api_key_here' else 'MISSING!'}")
    print("="*50)
    
    if not GROQ_KEY or GROQ_KEY == "your_groq_api_key_here":
        print("❌ WARNING: GROQ_API_KEY not configured!")
        print("   Set GROQ_API_KEY in your .env file")
    
    port = int(os.getenv('PORT', 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        threaded=True
    )
