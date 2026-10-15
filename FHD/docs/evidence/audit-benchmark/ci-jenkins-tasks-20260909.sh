#!/bin/bash
# R22 ci-release 域开源锚点实测：Jenkins 2.462.3 任务集 B1-B3（零插件 core-only）
set -u
J="http://127.0.0.1:18090"
JENH=/tmp/r22-jenkins/home
U=r22admin; P=r22pass123
CRUMB=$(curl -s --noproxy '*' -c /tmp/r22-jenkins/cj.txt -u $U:$P "$J/crumbIssuer/api/xml?xpath=concat(//crumbRequestField,\":\",//crumb)")
CK=$(echo "$CRUMB" | cut -d: -f2)
H=(-s --noproxy '*' -u "$U:$P" -H "Jenkins-Crumb:$CK" -c /tmp/r22-jenkins/cj.txt -b /tmp/r22-jenkins/cj.txt)

# 固定源码仓库（固定日期→确定性 SHA，可重复运行）
rm -rf /tmp/r22-git && mkdir -p /tmp/r22-git && cd /tmp/r22-git && git init -q . && git config user.email a@b && git config user.name a
echo "print('artifact-v1')" > build.py && git add -A
GIT_AUTHOR_DATE="2026-01-01T00:00:00 +0800" GIT_COMMITTER_DATE="2026-01-01T00:00:00 +0800" git commit -qm "src1"
SHA=$(git rev-parse HEAD)

mkjob() { # name config
  curl "${H[@]}" -o /dev/null -X POST "$J/job/$1/doDelete"
  curl "${H[@]}" -o /dev/null -w '%{http_code}' -X POST "$J/createItem?name=$1" -H "Content-Type:application/xml" --data "$2"
}

# ---------- B1 流水线从固定源码重建产物 ----------
CFG1='<?xml version="1.1" encoding="UTF-8"?>
<project>
  <description>r22-b1</description>
  <builders><hudson.tasks.Shell><command>rm -rf $WORKSPACE/src
git clone -q /tmp/r22-git $WORKSPACE/src
cd $WORKSPACE/src &amp;&amp; git checkout -q '"$SHA"'
git rev-parse HEAD &gt; $WORKSPACE/BUILT_SHA
python3 build.py &gt; $WORKSPACE/dist.txt</command></hudson.tasks.Shell></builders>
</project>'
mkjob r22-b1 "$CFG1" >/dev/null
curl "${H[@]}" -o /dev/null -X POST "$J/job/r22-b1/build"
RES=""; NUM=""
for i in $(seq 1 30); do
  sleep 4
  NUM=$(curl "${H[@]}" "$J/job/r22-b1/lastBuild/api/json?tree=number,result" | sed -nE 's/.*"number":([0-9]+).*/\1/p')
  RES=$(curl "${H[@]}" "$J/job/r22-b1/lastBuild/api/json?tree=number,result" | sed -nE 's/.*"result":"([^"]*)".*/\1/p')
  [ -n "$RES" ] && break
done
BSHA=$(curl "${H[@]}" "$J/job/r22-b1/ws/BUILT_SHA")
DIST=$(curl "${H[@]}" "$J/job/r22-b1/ws/dist.txt")
B1=FAIL; [ "$RES" = "SUCCESS" ] && [ "$BSHA" = "$SHA" ] && [ "$DIST" = "artifact-v1" ] && B1=PASS
echo "B1 $B1 res=$RES sha=$BSHA/$SHA dist=$DIST"

# ---------- B2 失败检查真实拦截（下游不跑） ----------
CFG2='<?xml version="1.1" encoding="UTF-8"?>
<project>
  <description>r22-fail</description>
  <builders><hudson.tasks.Shell><command>exit 1</command></hudson.tasks.Shell></builders>
  <publishers>
    <hudson.tasks.BuildTrigger>
      <childProjects>r22-down</childProjects>
      <threshold><name>SUCCESS</name><ordinal>0</ordinal></threshold>
    </hudson.tasks.BuildTrigger>
  </publishers>
</project>'
CFG3='<?xml version="1.1" encoding="UTF-8"?>
<project>
  <description>r22-down</description>
  <builders><hudson.tasks.Shell><command>echo ran &gt; $WORKSPACE/RAN</command></hudson.tasks.Shell></builders>
</project>'
mkjob r22-fail "$CFG2" >/dev/null
mkjob r22-down "$CFG3" >/dev/null
curl "${H[@]}" -o /dev/null -X POST "$J/job/r22-fail/build"
FRES=""
for i in $(seq 1 30); do
  sleep 4
  FRES=$(curl "${H[@]}" "$J/job/r22-fail/lastBuild/api/json?tree=result" | sed -nE 's/.*"result":"([^"]*)".*/\1/p')
  [ -n "$FRES" ] && break
done
sleep 4
DHTTP=$(curl "${H[@]}" -o /dev/null -w '%{http_code}' "$J/job/r22-down/lastBuild/api/json")
B2=FAIL; [ "$FRES" = "FAILURE" ] && [ "$DHTTP" = "404" ] && B2=PASS
echo "B2 $B2 fres=$FRES down_http=$DHTTP"

# ---------- B3 凭据/权限最小化与审计（core-only） ----------
# 3a 匿名不可读、未认证写操作被拒
ANON=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' "$J/api/json")
NOAUTH_WRITE=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' -X POST "$J/job/r22-b1/build")
# 3b 密码 bcrypt 散列存储（users 配置不回显明文）
LEAK=$(grep -rl "r22pass123" "$JENH"/users/ 2>/dev/null | wc -l | tr -d ' ')
HASHED=$(grep -l "jbcrypt" "$JENH"/users/*/config.xml 2>/dev/null | wc -l | tr -d ' ')
# 3c 构建审计：每次构建记录结果/时间/时长
BUILDS=$(curl -g "${H[@]}" "$J/job/r22-b1/api/json?tree=builds[number,result,duration,timestamp]")
HAS_META=$(echo "$BUILDS" | grep -c '"result"')
B3=FAIL
[ "$ANON" = "403" ] && [ "$NOAUTH_WRITE" = "403" ] && [ "$LEAK" = "0" ] && [ "$HASHED" -ge 1 ] && [ "$HAS_META" -ge 1 ] && B3=PASS
echo "B3 $B3 anon=$ANON noauth_write=$NOAUTH_WRITE leak=$LEAK hashed=$HASHED meta=$HAS_META"

echo "SUMMARY B1=$B1 B2=$B2 B3=$B3"
