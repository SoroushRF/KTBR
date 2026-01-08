from telegram import Update
from telegram.ext import ContextTypes
from config import OWNER_ID, processing_queue, active_tasks
from utils.auth import load_authorized_ids
from utils.queue_manager import get_server_status

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows bot status. Only for Owner.
    """
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        # Silently ignore or say unauthorized
        # Ghosting is better for security, but explicit deny is clearer for debug
        return 

    # Gather stats
    authorized_count = len(load_authorized_ids())
    server_stats = get_server_status()
    
    active_jobs = server_stats['active_jobs']
    queue_len = server_stats['queue_length']
    is_busy = server_stats['is_busy']
    
    # Format message
    msg = (
        f"📊 **System Status**\n\n"
        f"👥 **Users:** {authorized_count} authorized\n"
        f"⚙️ **Active Jobs:** {active_jobs} / {server_stats['max_jobs']}\n"
        f"⏳ **Queue Length:** {queue_len}\n"
        f"🔴 **Busy:** {is_busy}\n\n"
    )
    
    if active_tasks:
        msg += "**Current Tasks:**\n"
        for uid, task in active_tasks.items():
            msg += f"- User {uid} ({task.get('type', 'unknown')})\n"
        msg += "\n"
        
    if processing_queue:
        msg += "**Queue:**\n"
        for i, item in enumerate(processing_queue):
             msg += f"{i+1}. User {item['user_id']} ({item['file_size_mb']:.1f}MB)\n"

    await update.message.reply_text(msg, parse_mode="Markdown")
