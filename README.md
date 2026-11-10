# Grok Trader APK (cloud build)
1. Create a free GitHub account, make a NEW repository, upload everything in this folder
   (keep the .github/workflows/build.yml path).
2. Open the repo -> Actions tab -> "Build APK" -> wait ~3-5 min -> open the run -> download
   the artifact "GrokTrader-apk" (a zip containing app-debug.apk).
3. Install the APK on your phone (allow "install unknown apps").
4. The app is a window onto the bot: run `bash start.sh` in Termux first.
   First launch asks for the server address; default http://127.0.0.1:8080 (Termux).
   For a VPS, enter http://YOUR_SERVER_IP:8080 .
