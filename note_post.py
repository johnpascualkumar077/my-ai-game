"""
note.com 自動投稿スクリプト
使い方: python note_post.py
"""

import time
import json
import sys
import os
import re
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# 設定（ここを自分の情報に書き換える）
# ============================================================
EMAIL    = os.environ.get("NOTE_EMAIL", "your_email@example.com")
PASSWORD = os.environ.get("NOTE_PASSWORD", "your_password")
ARTICLE_FILE = "youware_note.md"   # 投稿するMarkdownファイル
PUBLISH = False  # True=即公開 / False=下書き保存
# ============================================================


def get_note_cookies(email: str, password: str) -> dict:
    """Seleniumでnoteにログインし、Cookieを返す"""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")          # ブラウザを画面に出したい場合はこの行を消す
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)

    try:
        driver.get("https://note.com/login")

        # メールアドレス入力
        email_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        email_input.send_keys(email)

        # パスワード入力
        password_input = driver.find_element(By.NAME, "password")
        password_input.send_keys(password)

        # ログインボタンをクリック
        login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
        login_button.click()

        # ログイン完了を待つ（URLが変わるまで待機）
        WebDriverWait(driver, 15).until(
            lambda d: d.current_url != "https://note.com/login"
        )
        time.sleep(2)  # 念のため追加待機

        # Cookieを辞書に変換して返す
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        print(f"[OK] ログイン成功（Cookie数: {len(cookies)}）")
        return cookies

    except Exception as e:
        print(f"[ERROR] ログイン失敗: {e}")
        driver.save_screenshot("login_error.png")  # スクリーンショットで確認用
        raise
    finally:
        driver.quit()


def markdown_to_html(md: str) -> str:
    """
    MarkdownをnoteのAPI用HTMLに変換（簡易版）。
    python-markdown がインストール済みならそちらを優先。
    """
    try:
        import markdown
        return markdown.markdown(md, extensions=["tables", "fenced_code"])
    except ImportError:
        pass

    # フォールバック：最低限の変換
    html = md

    # コードブロック
    html = re.sub(r"```[\w]*\n(.*?)```", r"<pre><code>\1</code></pre>", html, flags=re.DOTALL)

    # 見出し
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$",  r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$",   r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # 太字・斜体
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         html)

    # リンク
    html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)

    # 箇条書き
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

    # 水平線
    html = re.sub(r"^---$", r"<hr>", html, flags=re.MULTILINE)

    # 段落（空行区切り）
    paragraphs = html.split("\n\n")
    html = "\n".join(
        p if re.match(r"<(h[1-6]|ul|ol|li|pre|hr)", p.strip()) else f"<p>{p.strip()}</p>"
        for p in paragraphs if p.strip()
    )

    return html


def create_article(cookies: dict, title: str, markdown_content: str, publish: bool = False):
    """noteのAPIで記事を作成（下書きまたは公開）"""

    html_content = markdown_to_html(markdown_content)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://note.com/",
        "Origin":  "https://note.com",
    }

    payload = {
        "body":         html_content,
        "name":         title,
        "template_key": None,
    }

    # 記事を作成（下書き）
    resp = requests.post(
        "https://note.com/api/v1/text_notes",
        cookies=cookies,
        headers=headers,
        json=payload,
    )

    if resp.status_code != 200:
        print(f"[ERROR] 記事作成失敗: HTTP {resp.status_code}")
        print(resp.text[:500])
        return None, None

    result    = resp.json()
    article_id  = result["data"]["id"]
    article_key = result["data"]["key"]
    print(f"[OK] 下書き作成成功！ ID: {article_id}  key: {article_key}")
    print(f"     下書きURL: https://note.com/n/{article_key}/edit")

    # 公開する場合
    if publish:
        pub_resp = requests.post(
            f"https://note.com/api/v1/text_notes/{article_id}/publish",
            cookies=cookies,
            headers=headers,
            json={"publish_at": None, "price": 0},
        )
        if pub_resp.status_code == 200:
            print(f"[OK] 公開成功！")
            print(f"     公開URL: https://note.com/n/{article_key}")
        else:
            print(f"[WARN] 公開リクエスト失敗: HTTP {pub_resp.status_code}")
            print(pub_resp.text[:300])

    return article_id, article_key


def read_article(filepath: str) -> tuple[str, str]:
    """Markdownファイルを読んでタイトルと本文を返す"""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # 1行目の # タイトル を抜き出す
    lines  = content.splitlines()
    title  = lines[0].lstrip("# ").strip() if lines else "無題"
    body   = "\n".join(lines[1:]).strip()   # タイトル行を除いた本文
    return title, body


def main():
    # 認証情報チェック
    if EMAIL == "your_email@example.com":
        print("[ERROR] EMAIL と PASSWORD を設定してください")
        print("  環境変数で渡す場合: NOTE_EMAIL=xxx NOTE_PASSWORD=yyy python note_post.py")
        sys.exit(1)

    # 記事ファイルの読み込み
    if not os.path.exists(ARTICLE_FILE):
        print(f"[ERROR] ファイルが見つかりません: {ARTICLE_FILE}")
        sys.exit(1)

    title, body = read_article(ARTICLE_FILE)
    print(f"[INFO] 投稿する記事: 「{title}」")
    print(f"[INFO] 文字数: {len(body)}")

    # Cookieを取得してログイン
    print("\n[STEP 1] noteにログイン中...")
    cookies = get_note_cookies(EMAIL, PASSWORD)

    # 記事を投稿
    print("\n[STEP 2] 記事を投稿中...")
    article_id, article_key = create_article(cookies, title, body, publish=PUBLISH)

    if article_key:
        print("\n===== 完了 =====")
        if PUBLISH:
            print(f"公開URL: https://note.com/n/{article_key}")
        else:
            print(f"下書きURL: https://note.com/n/{article_key}/edit")
            print("※ PUBLISH = True にすると即公開できます")


if __name__ == "__main__":
    main()
