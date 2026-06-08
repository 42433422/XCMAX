#!/usr/bin/env bash
# 在**服务器**上以 root 执行。场景：曾出现「两个 V9 文件名」+ 重排为 V9=orders / V10=sync / V11=svip 后，PostgreSQL
# flyway_schema_history 中 version 9/10 仍对应**旧**脚本描述，Flyway 报 checksum 或 description mismatch，进程无法监听 8080。
# 处理：删除 version 9、10、11 的历史行（本仓库 sql 为幂等），mvn 打 JAR 后重启，由 Flyway 按**当前**文件重放 9~11。
# Usage: scp 到 /tmp/ 后 bash（或全量再跑一次 sync，避免 migration 树残留双份文件）
set -e
DP="/root/成都修茈科技有限公司/MODstore_deploy"
ENVF="$DP/.env"
JDIR="$DP/java_payment_service"
set -a
# shellcheck source=/dev/null
. "$ENVF" || { echo "[err] no $ENVF"; exit 1; }
set +a
U="${DATABASE_USER:-admin}"
export PGPASSWORD="${DATABASE_PASSWORD:?}"
echo "[ok] before:"
psql -U "$U" -d payment_db -h localhost -c "SELECT version, description, success FROM flyway_schema_history WHERE version::text IN ('9','10','11','12') ORDER BY installed_rank;" || true
psql -U "$U" -d payment_db -h localhost -v ON_ERROR_STOP=1 -c "DELETE FROM flyway_schema_history WHERE version::text IN ('9','10','11');"
echo "[ok] deleted 9,10,11; Flyway 将按当前 JAR 重放"
if [ -d "/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64" ]; then
  export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64"
  export PATH="$JAVA_HOME/bin:$PATH"
fi
cd "$JDIR" && mvn -B -q -DskipTests clean package
systemctl restart modstore-payment
sleep 6
for i in $(seq 1 25); do
  c=$(curl -sS -o /dev/null -m 2 -w "%{http_code}" http://127.0.0.1:8080/actuator/health 2>/dev/null || true)
  [ "$c" = "200" ] && { echo "pay=200"; psql -U "$U" -d payment_db -h localhost -c "SELECT version, description FROM flyway_schema_history WHERE version::text IN ('9','10','11') ORDER BY installed_rank;" 2>/dev/null; exit 0; }
  sleep 2
done
journalctl -u modstore-payment -n 35 --no-pager
exit 1
