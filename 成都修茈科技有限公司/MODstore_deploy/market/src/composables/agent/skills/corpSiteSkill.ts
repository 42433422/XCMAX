import type { AgentContext, SkillExecuteResult } from '../../../types/agent'
import { CORP_LINKS, getCorpPageKnowledge, linkForCorpPage, resolveCorpPageId } from '../../../content/siteKnowledge'

function reply(text: string): SkillExecuteResult {
  return { success: true, message: text, assistantReply: text }
}

function pageHintForPath(path: string): string {
  const pageId = resolveCorpPageId(path)
  const page = getCorpPageKnowledge(pageId)
  if (pageId === 'contact') return '您正在查看联系我们页，可直接填写需求表单预约方案沟通。'
  if (pageId === 'services') return '您正在产品中心，可了解各产品线与能力说明。'
  if (pageId === 'solutions') return '您正在解决方案页，可按行业查看场景与案例链接。'
  if (pageId === 'cases' || pageId.startsWith('case-')) return '您正在案例相关页面，可了解实践方向或进入详情。'
  if (pageId === 'news') return '您正在新闻资讯页，可查看公司动态与行业观察。'
  if (pageId === 'honors') return '您正在资质与能力页，了解研发、交付与安全服务机制。'
  if (pageId === 'excel-to-ai') return '您正在 Excel 体验工具页，可上传表格试识别；完整能力见产品中心。'
  if (pageId === 'developer') return '您正在开发者中心，可了解 API、集成与扩展入口。'
  if (pageId === 'download' || pageId === 'download-releases' || pageId === 'download-breakpoints' || pageId === 'download-goals') {
    return '您正在产品下载相关页，可问安装包、系统要求、进度看板或版本更新。'
  }
  if (pageId === 'world-will') return '您正在世界意志公司大厅，可查看 AI 员工编制与公开动态。'
  if (pageId === 'visualization') return '您正在可视化展示页，可了解产品与场景能力图示。'
  if (pageId === 'privacy') return '您正在隐私与服务协议页，可问数据处理或联系方式。'
  if (pageId === 'home') return '您正在官网首页，可了解 XCAGI 桌面与行业 Mod，并进入下载或预约沟通。'
  return `您正在「${page.title.replace(/\s*\|.*/, '')}」。${page.summary}`
}

/** 官网静态页：关键词应答（无需登录 / LLM） */
export function matchCorpSiteIntent(ctx: AgentContext): SkillExecuteResult | null {
  const q = ctx.userMessage.trim().toLowerCase()
  const path = ctx.route || ''

  if (/这页|页面|当前|干什么|介绍.*页/.test(q)) {
    const pageId = resolveCorpPageId(path)
    const page = getCorpPageKnowledge(pageId)
    const pageHint = pageHintForPath(path)
    const summary = ctx.pageSummary?.trim() || page.summary
    return reply(`${pageHint}\n\n${summary.slice(0, 320)}${summary.length > 320 ? '…' : ''}\n\n相关链接：${linkForCorpPage(pageId)}`)
  }
  if (/联系|咨询|预约|电话|微信|销售|合作|填表|表单/.test(q)) {
    return reply(
      `可以在这里留下需求，我们会尽快联系您：${CORP_LINKS.contact}\n\n也可直接说明您关心的场景（单据识别、标签打印、AI 工作台等），我帮您整理要点。`,
    )
  }
  if (/excel|上传|识别.*工具|试.*识别/.test(q)) {
    return reply(`可在此体验 Excel 上传识别：${CORP_LINKS.excelToAi}\n\n完整产品线见：${CORP_LINKS.services}`)
  }
  if (/下载|安装包|安装|xcagi|桌面端|macos|windows|android|安卓/.test(q)) {
    const page = getCorpPageKnowledge('download')
    return reply(
      `${page.summary}\n\n` +
        `打开产品下载页，按系统选择安装包：${CORP_LINKS.download}\n\n` +
        `也可看更新日志：${CORP_LINKS.downloadReleases}\n` +
        `需要授权或方案沟通：${CORP_LINKS.contact}`,
    )
  }
  if (/产品|服务|功能|单据|标签|打印|modstore|市场/.test(q) && !/案例|下载/.test(q)) {
    const page = getCorpPageKnowledge('services')
    return reply(`${page.summary}\n\n详见产品中心：${CORP_LINKS.services}\n\n想深入某一场景可看解决方案：${CORP_LINKS.solutions}`)
  }
  if (/方案|制造|贸易|园区|教育|行业|场景/.test(q) && !/案例|详情/.test(q)) {
    return reply(
      `解决方案覆盖制造贸易、园区服务、教育协同与企业 AI 工作流。可打开解决方案页继续看：${CORP_LINKS.solutions}\n\n` +
        `也可直接看案例：制造（${CORP_LINKS.caseManufacture}）、园区（${CORP_LINKS.casePark}）、教育（${CORP_LINKS.caseEdu}）。`,
    )
  }
  if (/制造|生产|库存/.test(q) && /案例|详情/.test(q)) {
    const page = getCorpPageKnowledge('case-manufacture')
    return reply(`${page.summary}\n\n详情页：${CORP_LINKS.caseManufacture}\n更多案例：${CORP_LINKS.cases}`)
  }
  if (/园区/.test(q) && /案例|详情/.test(q)) {
    const page = getCorpPageKnowledge('case-park')
    return reply(`${page.summary}\n\n详情页：${CORP_LINKS.casePark}\n更多案例：${CORP_LINKS.cases}`)
  }
  if (/校园|教育|移动服务/.test(q) && /案例|详情|服务/.test(q)) {
    const page = getCorpPageKnowledge('case-edu')
    return reply(`${page.summary}\n\n详情页：${CORP_LINKS.caseEdu}\n更多案例：${CORP_LINKS.cases}`)
  }
  if (/案例|客户/.test(q)) {
    return reply(
      `我们整理了制造、园区、教育等客户案例，可在案例中心浏览摘要与详情：${CORP_LINKS.cases}\n\n` +
        `制造：${CORP_LINKS.caseManufacture}\n园区：${CORP_LINKS.casePark}\n教育：${CORP_LINKS.caseEdu}`,
    )
  }
  if (/新闻|资讯|动态|行业观察/.test(q)) {
    return reply(`最新新闻与行业观察见：${CORP_LINKS.news}`)
  }
  if (/资质|能力|证照|认证|交付|安全/.test(q)) {
    const page = getCorpPageKnowledge('honors')
    return reply(`${page.summary}\n\n详见：${CORP_LINKS.honors}（具体资质以实际公示为准）`)
  }
  if (/市场|登录|注册|会员|工作台|试用/.test(q)) {
    return reply(`登录 AI 市场可体验完整工作台与数字管家能力：${CORP_LINKS.market}\n\n若尚未注册，可先预约方案沟通：${CORP_LINKS.contact}`)
  }
  if (/购买|怎么买|如何买|下单|开通|买会员|买套餐|授权/.test(q) || /价格|报价|费用|多少钱|收费|会员.*价/.test(q)) {
    const plans = `${CORP_LINKS.market.replace(/\/$/, '')}/plans`
    return reply(
      `购买与开通路径：\n` +
        `1. 注册/登录 AI 市场：[点我跳转](${CORP_LINKS.market})\n` +
        `2. 会员方案选套餐并支付：[点我跳转](${plans})\n` +
        `3. 企业定制或批量授权，预约沟通：[点我跳转](${CORP_LINKS.contact})\n` +
        `4. 桌面端/客户端授权说明：[点我跳转](${CORP_LINKS.download})`,
    )
  }
  if (/公司|修茈|关于|是谁|介绍/.test(q)) {
    const page = getCorpPageKnowledge('about')
    return reply(`${page.summary}\n\n了解更多：${CORP_LINKS.about}`)
  }
  if (/注册|账号|开户/.test(q)) {
    return reply(`注册 AI 市场账号：${CORP_LINKS.market}register\n\n也可先预约沟通：${CORP_LINKS.contact}`)
  }
  return null
}
