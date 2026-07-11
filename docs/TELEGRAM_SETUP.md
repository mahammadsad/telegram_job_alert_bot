# Telegram setup

1. In Telegram open verified **@BotFather**, send `/newbot`, and follow the prompts.
2. Copy the bot token into GitHub secret `TELEGRAM_BOT_TOKEN`.
3. Create a channel, open **Administrators → Add Admin**, add the bot, and allow posting.
4. For a public channel use `@channel_username` as `TELEGRAM_CHANNEL_ID`.
5. For review alerts, message the bot from a private admin chat, obtain the numeric chat
   ID with Telegram's `getUpdates` method, and save it as `TELEGRAM_REVIEW_CHAT_ID`.
6. Run a GitHub Actions dry run first. Then manually run production with one safe item.

Successful deliveries are recorded as `PHOTO_SENT`, `TEXT_SENT`, `FULLY_SENT`,
`PARTIAL_FAILURE`, or `FAILED`. If a split caption fails after the photo, the next
retry reuses the recorded photo ID and sends only the missing text. Admins can inspect
`telegram_posts` in the dashboard before retrying or manually deleting a partial post.
