export type OnboardingIndustryCategoryId =
  | 'manufacturing'
  | 'commerce'
  | 'construction'
  | 'technology'
  | 'business-services'
  | 'consumer-services'
  | 'health-education'
  | 'agriculture-energy'
  | 'public-organizations'

export type OnboardingIndustryCategory = {
  id: OnboardingIndustryCategoryId
  label: string
  icon: string
}

export type OnboardingIndustryOption = {
  id: string
  name: string
  scenario: string
  categoryId: OnboardingIndustryCategoryId
  aliases: string[]
  popular?: boolean
}

export const ONBOARDING_INDUSTRY_CATEGORIES: readonly OnboardingIndustryCategory[] = [
  { id: 'manufacturing', label: '制造工业', icon: 'fa-industry' },
  { id: 'commerce', label: '商贸流通', icon: 'fa-shopping-bag' },
  { id: 'construction', label: '建筑地产', icon: 'fa-building-o' },
  { id: 'technology', label: '科技传媒', icon: 'fa-microchip' },
  { id: 'business-services', label: '企业服务', icon: 'fa-briefcase' },
  { id: 'consumer-services', label: '生活服务', icon: 'fa-coffee' },
  { id: 'health-education', label: '医疗教育', icon: 'fa-heartbeat' },
  { id: 'agriculture-energy', label: '农业能源', icon: 'fa-sun-o' },
  { id: 'public-organizations', label: '公共组织', icon: 'fa-university' },
] as const

const option = (
  id: string,
  name: string,
  scenario: string,
  categoryId: OnboardingIndustryCategoryId,
  aliases: string[] = [],
  popular = false,
): OnboardingIndustryOption => ({ id, name, scenario, categoryId, aliases, popular })

/**
 * 入门页使用的用户行业语言，不等同于已经上架的行业 Mod。
 * 没有专属包的行业仍会进入通用 AI 配置，后续可继续生成或安装能力。
 */
export const ONBOARDING_INDUSTRY_OPTIONS: readonly OnboardingIndustryOption[] = [
  option('通用', '综合型企业', '跨行业经营或暂时不确定主要方向', 'business-services', ['通用', '其他', '综合'], true),

  option('制造业', '制造业', '生产、采购、库存与质量管理', 'manufacturing', ['工厂', '生产加工', '工业'], true),
  option('机械设备', '机械与设备制造', '设备、零部件、工单与售后', 'manufacturing', ['机械', '机加工', '装备制造']),
  option('电子电器', '电子与电器制造', '物料、BOM、生产与质检', 'manufacturing', ['电子', '电器', '3C', '消费电子']),
  option('汽车', '汽车与零部件', '汽配、生产、渠道与售后', 'manufacturing', ['汽车制造', '汽配', '零部件']),
  option('新能源装备', '新能源与装备', '储能、光伏、设备与项目交付', 'manufacturing', ['新能源', '光伏', '锂电', '储能']),
  option('涂料', '涂料与新材料', '配方、批次、库存、渠道与出货', 'manufacturing', ['油漆', '化工涂料'], true),
  option('化工', '化工与新材料', '批次、质检、仓储与安全管理', 'manufacturing', ['化学品', '新材料', '精细化工']),
  option('食品制造', '食品与饮料制造', '原料、批次、保质期与渠道', 'manufacturing', ['食品', '饮料', '食品加工']),
  option('纺织服装', '纺织与服装', '款式、面辅料、生产与订单', 'manufacturing', ['纺织', '服装', '鞋帽']),
  option('医药制造', '医药与医疗器械', '批次、质量、合规与流通', 'manufacturing', ['制药', '医疗器械', '药品']),
  option('包装印刷', '包装与印刷', '订单、材料、排产与交付', 'manufacturing', ['印刷', '包装', '标签']),
  option('家居制造', '家居与家具制造', '定制、物料、生产与安装', 'manufacturing', ['家具', '家居', '定制家居']),

  option('批发', '批发与分销', '客户、价格、库存与出货', 'commerce', ['分销', '经销', '贸易'], true),
  option('电商', '电商与零售', '商品、订单、会员与履约', 'commerce', ['零售', '网店', '直播电商'], true),
  option('连锁零售', '连锁零售', '门店、商品、会员与调拨', 'commerce', ['连锁店', '商超', '便利店']),
  option('进出口', '进出口贸易', '询报价、合同、单证与结算', 'commerce', ['外贸', '国际贸易', '报关']),
  option('供应链贸易', '供应链与贸易', '采购、销售、仓储与资金协同', 'commerce', ['供应链', '大宗贸易']),
  option('汽车流通', '汽车销售与服务', '车辆、客户、门店与售后', 'commerce', ['4S店', '汽贸', '汽车服务']),
  option('农产品流通', '农产品流通', '产地、批次、仓储与分销', 'commerce', ['生鲜', '农贸', '农产品']),
  option('物流', '物流与运输', '运单、车辆、线路与结算', 'commerce', ['运输', '货运', '快递'], true),
  option('仓储配送', '仓储与配送', '仓库、库存、波次与配送', 'commerce', ['仓储', '配送', '三方仓']),

  option('建筑工程', '建筑与工程施工', '项目、合同、进度与成本', 'construction', ['建筑', '施工', '工程'], true),
  option('工程安装', '工程安装与维保', '项目、设备、工单与服务', 'construction', ['安装工程', '机电工程', '维保']),
  option('房地产', '房地产开发', '项目、房源、客户与回款', 'construction', ['地产', '房地产开发']),
  option('物业', '物业与园区运营', '空间、业主、收费与工单', 'construction', ['物业管理', '园区', '写字楼']),
  option('装修设计', '装饰装修与设计', '客户、方案、预算与施工', 'construction', ['装修', '室内设计', '装潢']),
  option('建材', '建材与家居流通', '商品、门店、项目与配送', 'construction', ['建筑材料', '家装建材']),

  option('软件信息', '软件与信息技术', '项目、客户、研发与服务交付', 'technology', ['软件', 'IT', '信息化', 'SaaS'], true),
  option('人工智能', '人工智能与数据服务', '模型、数据、项目与算力服务', 'technology', ['AI', '大模型', '数据服务']),
  option('互联网', '互联网与平台服务', '用户、内容、交易与运营', 'technology', ['互联网平台', '平台经济']),
  option('通信', '通信与数字基础设施', '客户、资源、项目与运维', 'technology', ['电信', '通信服务', 'IDC']),
  option('文化传媒', '文化传媒与内容', '内容、版权、项目与商业合作', 'technology', ['传媒', '影视', '出版', '自媒体']),
  option('广告创意', '广告与创意服务', '客户、项目、素材与投放', 'technology', ['广告', '营销', '公关']),
  option('科研技术', '科研与技术服务', '课题、项目、成果与知识资产', 'technology', ['科研', '检测', '认证', '技术服务']),

  option('企业服务', '企业服务', '客户、项目、合同与交付', 'business-services', ['B2B服务', '商业服务']),
  option('咨询', '咨询与管理服务', '客户、项目、方案与工时', 'business-services', ['管理咨询', '顾问']),
  option('财税', '财税与会计服务', '客户、账期、申报与服务进度', 'business-services', ['会计', '税务', '代理记账']),
  option('法律', '法律服务', '客户、案件、合同与知识库', 'business-services', ['律师', '律所', '法务']),
  option('人力资源', '人力资源服务', '招聘、员工、考勤与薪酬', 'business-services', ['HR', '招聘', '劳务', '考勤', '排班']),
  option('金融', '金融与保险服务', '客户、产品、流程与合规', 'business-services', ['银行', '保险', '证券', '基金']),
  option('租赁', '租赁与资产服务', '资产、合同、租期与结算', 'business-services', ['设备租赁', '汽车租赁']),
  option('会展', '会展与商务活动', '客户、场地、项目与供应商', 'business-services', ['展会', '会议', '活动执行']),

  option('餐饮', '餐饮与门店', '门店、菜品、采购与经营分析', 'consumer-services', ['饭店', '餐厅', '茶饮'], true),
  option('酒店', '酒店与住宿', '房态、客人、服务与收益', 'consumer-services', ['住宿', '民宿', '宾馆']),
  option('旅游文体', '旅游、体育与娱乐', '产品、场地、会员与活动', 'consumer-services', ['旅游', '体育', '娱乐', '健身']),
  option('生活服务', '居民与生活服务', '客户、预约、服务与结算', 'consumer-services', ['本地生活', '维修', '洗护']),
  option('美容健康', '美容与健康服务', '客户、预约、项目与会员', 'consumer-services', ['美业', '美容院', '养生']),
  option('家政', '家政与社区服务', '人员、订单、排班与评价', 'consumer-services', ['保洁', '家政服务', '社区服务']),

  option('医疗健康', '医疗与健康服务', '患者、预约、服务与合规', 'health-education', ['医院', '诊所', '健康管理']),
  option('教育', '教育与培训', '学员、课程、排课与教务', 'health-education', ['学校', '培训机构', '职业教育']),
  option('养老护理', '养老与护理', '长者、床位、照护与家属服务', 'health-education', ['养老院', '护理', '康养']),
  option('社会服务', '社会工作与服务', '服务对象、项目、活动与记录', 'health-education', ['社工', '公益服务']),

  option('农业', '农业与种植', '基地、农资、生产与销售', 'agriculture-energy', ['种植业', '农场', '农资']),
  option('林牧渔业', '林业、牧业与渔业', '养殖、批次、投入品与销售', 'agriculture-energy', ['林业', '畜牧', '水产', '养殖']),
  option('能源电力', '能源与电力', '项目、设备、巡检与交易', 'agriculture-energy', ['电力', '燃气', '能源']),
  option('环保水务', '环保与水务', '项目、监测、设备与运维', 'agriculture-energy', ['环保', '水处理', '固废']),
  option('采矿资源', '采矿与资源', '矿区、生产、设备与安全', 'agriculture-energy', ['矿业', '资源开采']),

  option('政府事业', '政府与公共事业', '事项、项目、资产与协同', 'public-organizations', ['政府', '事业单位', '公共服务']),
  option('社会组织', '协会与社会组织', '会员、项目、活动与服务', 'public-organizations', ['协会', '商会', '基金会', '非营利']),
  option('园区运营', '园区与产业服务', '企业、空间、政策与服务事项', 'public-organizations', ['产业园', '孵化器', '开发区']),
  option('公用设施', '公共设施运营', '设施、巡检、工单与应急', 'public-organizations', ['市政', '公共设施', '城市服务']),
] as const

export function listOnboardingIndustryOptions(): OnboardingIndustryOption[] {
  return ONBOARDING_INDUSTRY_OPTIONS.map((item) => ({ ...item, aliases: [...item.aliases] }))
}
