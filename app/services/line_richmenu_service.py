import requests
import json
import os
from typing import Optional

def upload_and_set_default_richmenu(access_token: str):
    """
    上傳 Rich Menu 並設定為預設
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # 1. 定義 Rich Menu 結構 (直接使用 richmenu.json 的內容)
    richmenu_data = {
        "size": {
          "width": 2500,
          "height": 843
        },
        "selected": True,
        "name": "客服切換選單",
        "chatBarText": "切換客服模式",
        "areas": [
          {
            "bounds": { "x": 0, "y": 0, "width": 1250, "height": 843 },
            "action": {
              "type": "postback",
              "data": "action=change_mode&mode=ai",
              "displayText": "切換為【AI客服】"
            }
          },
          {
            "bounds": { "x": 1250, "y": 0, "width": 1250, "height": 843 },
            "action": {
              "type": "postback",
              "data": "action=change_mode&mode=human",
              "displayText": "切換為【真人客服】"
            }
          }
        ]
    }

    # Step 1: 建立 rich menu
    response = requests.post(
        'https://api.line.me/v2/bot/richmenu',
        headers=headers,
        json=richmenu_data
    )

    if response.status_code != 200:
        print(f'❌ 建立 RichMenu 失敗: {response.text}')
        return None

    richmenu_id = response.json()["richMenuId"]
    print(f'✅ RichMenu ID: {richmenu_id}')

    # Step 2: 上傳圖片
    # 使用相對路徑計算圖片位置 (位於 app/images/origin.png)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    image_path = os.path.join(base_dir, "images", "origin.png")
    if not os.path.exists(image_path):
        print(f'❌ 圖片不存在: {image_path}')
        return None

    headers_img = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "image/png"
    }

    with open(image_path, 'rb') as f:
        image_response = requests.post(
            f'https://api-data.line.me/v2/bot/richmenu/{richmenu_id}/content',
            headers=headers_img,
            data=f
        )

    if image_response.status_code != 200:
        print(f'❌ 上傳圖片失敗: {image_response.text}')
        return None
    
    print('✅ 圖片上傳成功')

    # Step 3: 設定為預設 rich menu
    set_default = requests.post(
        f'https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}',
        headers=headers
    )

    if set_default.status_code != 200:
        print(f'❌ 設為預設失敗: {set_default.text}')
        return None
    
    print('✅ 設為預設 RichMenu 成功！')
    return richmenu_id
