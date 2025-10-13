#!/usr/bin/sh
cd /root/cota
echo '开始拉取最新代码...'
git pull
echo '代码更新完成，开始kill老服务'
p=$(ps x | grep cota | grep -v 'grep' | awk '{print $1}')
if [ "$p" != "" ]; then
    kill -9 $p
fi
echo '开始启动新服务...'
old_log_file=logs/log_$(date +%s).txt
log_file=logs/log.txt
if [ -e "$log_file" ]; then
    mv "$log_file" "$old_log_file"
fi
nohup poetry run cota run --channel=websocket --config=cota/bots/simplebot --host=0.0.0.0 --port=5005  > $log_file 2>&1 &
sleep 3
suc=$(cat $log_file | grep "Starting worker" | wc -l)
if [ "$suc" = "1" ]; then
    echo '重启成功'
else
   echo '重启失败，错误信息如下：'
   cat $log_file
fi
