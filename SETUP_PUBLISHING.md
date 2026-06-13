# Publishing setup

Clipmaker can auto-upload approved clips. Nothing is published until you complete the
steps below **and** set `enabled: true` for the platform in `config.yaml`. YouTube
uploads default to **private** so your first tests are safe.

All secrets live in a git-ignored `secrets/` folder in the project root.

---

## YouTube Shorts (full auto-upload)

1. Go to <https://console.cloud.google.com/> and create a project (e.g. "Clipmaker").
2. **APIs & Services → Library →** enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen:** choose *External*, fill the basics, add
   your own Google account under **Test users** (so you don't need Google verification).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →**
   Application type **Desktop app**. Download the JSON.
5. Save that file as `secrets/client_secret.json` in the project.
6. In `config.yaml` set:
   ```yaml
   publish:
     youtube:
       enabled: true
       privacy: private   # switch to public when you're happy
   ```
7. The **first** time a clip publishes, a browser opens asking you to authorize. After
   that the token is saved to `secrets/youtube_token.json` and uploads are silent.

**Quota note:** the free YouTube API quota allows roughly **6 uploads/day**. Plenty for
personal use; if you need more you can request a quota increase.

---

## TikTok (push to drafts)

Full public auto-posting requires TikTok to **audit** your developer app. Until then,
clips can be pushed to your TikTok **inbox/drafts** and you tap *Post* in the app.

1. Create an app at <https://developers.tiktok.com/> and add the **Content Posting API**.
2. Complete the login/OAuth so you have a **user access token** with the
   `video.upload` scope.
3. Save it as `secrets/tiktok_token.json`:
   ```json
   { "access_token": "PASTE_TOKEN_HERE" }
   ```
4. In `config.yaml` set `publish.tiktok.enabled: true`.

> TikTok access tokens expire; when posting starts failing, refresh the token. A guided
> TikTok login helper can be added later once your dev app exists.
