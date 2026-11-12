#!/bin/zsh
# 一键重建「设备」面板（幂等，可反复执行 / 可挂定时任务）
#
# 流水线：
#   1. 刷新 HA 访问令牌
#   2. 同步脚本到 NAS
#   3. NAS 拉快照 -> 生成配置（输出缺图清单与差分报告）
#   4. 本地按缺图清单抓百科图 -> 标准化 -> 上传 NAS
#   5. NAS 重新生成 -> 写入面板 -> 破缓存 -> 校验
#
# 依赖：ssh 别名 fnos 指向 NAS；HA 配置目录在 NAS 上
set -e
cd "$(dirname "$0")"

NAS_HOST=fnos
NAS_WORK=/tmp/mi-cards
NAS_WWW=/vol1/1000/docker/haos/www
NAS_STATE=/vol1/1000/docker/haos/.mi-cards/state.json
LOCAL_RAW=/tmp/mi-img-raw
LOCAL_OUT=/tmp/mi-img-work
DASH=device-cards

# 远端统一环境（生成器要能看见已上线的图片）
REMOTE_ENV="MI_WORK_DIR=$NAS_WORK MI_STATE_FILE=$NAS_STATE MI_IMG_DIRS=$NAS_WWW/mi-images MI_WWW_DIR=$NAS_WWW MI_DASH_PATH=$DASH"

echo "==> 1/6 刷新访问令牌"
python3 refresh_tokens.py

echo "==> 2/6 同步脚本到 NAS"
ssh -o ConnectTimeout=8 $NAS_HOST "mkdir -p $NAS_WORK $NAS_WWW/mi-images $(dirname $NAS_STATE)"
scp -q -o ConnectTimeout=8 ha_ws.py pull_state.py gen_dashboard.py sync_state.py \
    deploy_device_dashboard.py bump_resource_version.py mi-cards.js sync.py $NAS_HOST:$NAS_WORK/
python3 - <<'PY' | ssh -o ConnectTimeout=8 fnos "cat > $NAS_WORK/ha_token.txt"
import json
print(json.load(open("/tmp/ha_tokens.json"))["access_token"])
PY

echo "==> 3/6 NAS 拉快照并生成配置"
ssh -o ConnectTimeout=8 $NAS_HOST "cd $NAS_WORK && $REMOTE_ENV python3 sync.py --stage snapshot && $REMOTE_ENV python3 sync.py --stage generate"

echo "==> 4/6 补齐缺失的产品图"
ssh -o ConnectTimeout=8 $NAS_HOST "cat $NAS_WORK/mi-missing-models.json" > /tmp/mi-missing-models.json
NEED=$(python3 -c "import json;print(len(json.load(open('/tmp/mi-missing-models.json'))))")
if [ "$NEED" -gt 0 ]; then
  echo "    $NEED 个型号缺图，抓取百科原图..."
  python3 fetch_raw_images.py --missing /tmp/mi-missing-models.json --out $LOCAL_RAW
  python3 normalize_images.py --src $LOCAL_RAW --out $LOCAL_OUT --nas "$NAS_HOST:$NAS_WWW/mi-images"
else
  echo "    全部设备都有产品图，跳过"
fi

echo "==> 5/6 重新生成并写入面板"
ssh -o ConnectTimeout=8 $NAS_HOST "cd $NAS_WORK && $REMOTE_ENV python3 sync.py --stage generate && $REMOTE_ENV python3 sync.py --stage deploy"

echo "==> 6/6 校验"
ssh -o ConnectTimeout=8 $NAS_HOST "cd $NAS_WORK && $REMOTE_ENV python3 sync.py --stage verify"

echo ""
echo "完成。面板地址: http://192.168.31.67:8123/$DASH"
