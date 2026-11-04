# 暂停状态下的 Excel 模型提示词与修改文件审查

已提交 HEAD：b5b97ad64c010f966a8eed697d8183ef473884ee；本地还有 10 个已跟踪修改和 7 个未跟踪新文件，下列内容为当前工作树，不等于 PR 已提交内容。
已跟踪文件 diff SHA-256：97f9494124953fc8a6718ff77a207fddde1060449a8d543b1f1740c4d9ef4601（不含未跟踪文件；每个文件另列哈希）。

当前文件调用关系：接口 reviewed_excel_classification_analyze → 分类 _classify_semantic_batch → reference_ids.prepare_reference_messages → 模型；多批且完成覆盖后调用 grouping.group_semantic_fragments。导出 _auto_slices → derive_classified_documents → derive_document_workbook → formula_support。audit 在请求前后记录。绘图专项尚未接入此工作树。

原先的独立 reviewed_excel_contract.py 原型已移出产品树并保留在 /workspace/luna-test/reviewed_excel_contract-prototype.py；当前共用提示与哈希校验位于新增 reviewed_excel_reference_ids.py，见下列清单。

## 当前修改文件及 SHA-256

1. FHD/app/application/etl/llm_assist_runtime.py — LlmAssistResult 增加实际 provider 字段。
   SHA-256 `6aba1cc909873c0f10f71b7c727e545477aa76c0b720606dc9fcab90b635ba33`
2. FHD/app/application/reviewed_excel_auto_slice.py — derive_classified_documents/_slice_filename：仅对已分组且闭合的模型单据产出中文名称工作簿，检查依赖。
   SHA-256 `ebaa5451da0b12ed64788feb708db9448a3a18a3f3b104e54b09e2a4fbafa566`
3. FHD/app/application/reviewed_excel_classification.py — _classify_semantic_batch/combine_semantic_batches：构造和校验模型输入输出、分批覆盖及模型片段；旧规则也在文件中。
   SHA-256 `c0408feadc90e1c998245899ac625a555371a713d161bb57725dbd4266924183`
4. FHD/app/application/reviewed_excel_evidence.py — candidate_fragment_links/plan_semantic_batches/build_rule_hints：证据、分批及关系；保留旧规则提示构造函数，自动输入前被移除。
   SHA-256 `8f3d8bd3b7fe5aa19bd41f3ab0962bc326e88cd3d78104ab1989f746a9a317b3`
5. FHD/app/application/reviewed_excel_grouping.py — prepare_grouping/group_semantic_fragments/validate_grouping：用已读原始事实及模型自己的片段结果进行第二阶段分组。
   SHA-256 `27ebdc85175df4662047636781e7fab3f3a2c991065ca79a059f0a34311ed56b`
6. FHD/app/application/reviewed_excel_template.py — _template_mimo_complete/derive_document_workbook：模型适配器、裁切及依赖支撑工作表。
   SHA-256 `b4d85b5cc5bf01796cae40db7cb1925667201d9fb42bb76bd5e99384814b48c8`
7. FHD/app/domain/shared_services/conversation/llm_adapter.py — OpenAICompatibleAdapter.chat_completion：发送后、解析前回调记录响应，不记录请求认证头。
   SHA-256 `b239ea67d94fbba728e78c13b284ab9ee4dda667bbf529e7602846bb2ae8853d`
8. FHD/app/fastapi_routes/reviewed_excel_template.py — reviewed_excel_classification_analyze/_auto_slices/_response_audit_writer：分类接口、状态和归档、自动裁切接口。
   SHA-256 `418d1fc8ca3502bdf77f808bc26cdc9bf1bde1d09bf3c59f583662e5367e3439`
9. FHD/tests/test_application/test_reviewed_excel_auto_slice.py — 自动裁切、分组、公式支撑等合成测试变更。
   SHA-256 `c9ba2f457215f31f5b0be9ad8b49ccea7d438e36833c097cede6f14d9f7da0c1`
10. FHD/tests/test_application/test_reviewed_excel_template.py — 分类、模型返回和归档等接口合成测试变更。
   SHA-256 `e7f86caae3dbd9a83f7cbeb4684601af7a9d3f14388c9ba38ea06cc5aff2a2df`
11. FHD/app/application/reviewed_excel_audit.py — 新增：claim_request/record_response/capture_response；请求与响应的归档状态及哈希。
   SHA-256 `b2c12b5fcabded5837ce470340dcd77ff24eedabe239813eee86a83b2d75a800`
12. FHD/app/application/reviewed_excel_formula_support.py — 新增：plan_formula_support/install_formula_support；计算同表静态依赖、生成支撑表。
   SHA-256 `1cc0a5b00223a344c284efc9e1e64f9c8584e96799a61981ca9281107ce0b38f`
13. FHD/app/application/reviewed_excel_reference_ids.py — 新增：reference_contract/prepare_reference_messages/neutralize_messages/contract_hashes/verify_contract 等。所谓“共用提示词”实际存于此文件的 IDENTIFY_PROMPT、GROUP_PROMPT 常量；并没有新增独立服务或配置平台。该文件本身是新模块。
   SHA-256 `9f48d59ea14d4cd3361787be12db583bb56c7ac48722d3732228740c5d32df52`
14. FHD/tests/test_application/test_reviewed_excel_audit.py — 新增：归档与响应采集测试。
   SHA-256 `70e504ab7f9dedfb61d508754f0dae52f2d58bc07a3e3a9790db6b40c81c7014`
15. FHD/tests/test_application/test_reviewed_excel_contract.py — 新增：不同合成输入使用相同提示及结构模板哈希测试。
   SHA-256 `2ead3bcedcfc5a005299a7bfcca0112ea583d557a932d6961297d11deb2374f7`
16. FHD/tests/test_application/test_reviewed_excel_formula_support.py — 新增：公式依赖规划、支撑表测试。
   SHA-256 `a7851cef07cc5afe05ad54988bf65573f7edcadc29ad3c30756cd8ed79026226`
17. FHD/tests/test_application/test_reviewed_excel_reference_ids.py — 新增：证据编号与模型输入构造测试。
   SHA-256 `b953c75723d4c824a9a3d3a117ed86d71d1f43f537030fea291112697bd9542a`

## 自动识别 system：当前完整英文原文

Identify physical fragments and group them into logical documents using only the supplied source cells and structure. Do not assume a document count or infer a business boundary from a transport batch or sheet boundary. Leave uncertain fragments ungrouped. Do not use unread content as evidence. Keep merged cells intact; every evidence coordinate MUST be inside its region and on the same sheet. External context belongs in dependencies. A repeated table header is an observation, not proof of continuation or a business category. Treat structural observations, not proof, as context only. Return exactly one JSON object matching output_schema, without extra fields. Use only supplied evidence_id values for evidence_ids, dependency_ids and primary_id. The primary_id must identify a non-context cell inside its region. For each region cite only a small set of representative evidence IDs, at most 100; do not list every cell. Include only necessary dependency IDs, also at most 100. Integrity constraints show primary row spans, direct formula references and known merged ranges. Do not sever merged ranges or treat formula references as proof of one business document. Unresolved references and omitted merges require caution; unread cells are not evidence.

### 完整中文逐句翻译

仅根据提供的源单元格和结构识别物理片段，并将它们分组为逻辑单据。不要假定单据数量，也不要从传输批次或工作表边界推断业务边界。将不确定的片段保持为未分组。不要把未读取的内容用作证据。保持合并单元格完整；每个证据坐标必须位于对应区域内且属于同一工作表。外部上下文应放在依赖项中。重复表头只是观察结果，不构成续页或业务类别的证明。把结构观察仅作为上下文，而不是证明。严格返回一个符合 output_schema 的 JSON 对象，不要添加额外字段。只能使用所提供的 evidence_id 值作为 evidence_ids、dependency_ids 和 primary_id。primary_id 必须指向该区域内一个非上下文单元格。每个区域只引用少量有代表性的证据编号，最多 100 个；不要列出每一个单元格。只列必要的依赖编号，同样最多 100 个。完整性约束展示主体行的行区间、直接公式引用和已知合并区域。不要切断合并区域，也不要将公式引用当作属于同一业务单据的证明。未解析的引用和省略的合并区域需要谨慎；未读取的单元格不是证据。

## 二阶段分组 system：当前完整英文原文

Group only fragments that belong to the same business document. A standalone fragment can be one group. Do not group merely because fragments are adjacent, have similar headers, or share a category. Leave uncertain fragments ungrouped. For every grouped fragment cite at least one sent cell within it and explain the relationship using sent values. Use only supplied region_id and evidence_id values. Fragment boundaries are fixed; do not invent ranges or cells. Return exactly one JSON object matching output_schema.

### 完整中文逐句翻译

仅将属于同一业务单据的片段分在一起。一个独立片段也可以单独成为一个组。不要仅因为片段相邻、表头相似或类别相同就将它们分组。将不确定的片段保持为未分组。每个已分组片段至少引用一个发给模型且位于该片段内的单元格，并使用发送的值说明它们的关系。只能使用所提供的 region_id 和 evidence_id。片段边界已固定；不要编造范围或单元格。严格返回一个符合 output_schema 的 JSON 对象。

## 自动识别 user 消息结构

user 内容是一个 JSON 对象，而非另一段自由文本提示。当前自动模式包含下列动态字段：

- `output_schema`：下文识别结构；实际工作表名与证据编号由该批原始数据生成。
- `sheets`：原工作表名、行列数、合并区域及遗漏数、显隐状态、隐藏行列统计和有限列表；并非单据候选。
- `batch_coverage`：每表总非空格数、本批主体非空格数、重复上下文数和未读数。
- `cells`：每条原始事实包含 `sheet`、`cell`、`value`、`kind`、`context_only` 和程序顺序分配的 `evidence_id`。大文件的部分首尾单元格会被标为重复上下文；它们不是业务分割答案。
- `integrity_constraints`：`primary_rows` 为主体行区间；`formula_references` 为主体公式的静态引用及无法解析标记；`merged_ranges` 为已送出的原始合并范围及遗漏数。

自动模式发送前删除 `rule_hints`、`structure_map`、`relationship_context`、`labels`。代码仍会先在内存构造旧规则与旧消息，但自动消息会被替换；旧规则结果还可能在后验结构中出现，已标为程序观察。

## 自动识别输出 JSON Schema（动态枚举以占位符表示）

```json
{
  "type": "object",
  "required": [
    "physical_regions",
    "logical_documents",
    "layout_references"
  ],
  "additionalProperties": false,
  "properties": {
    "physical_regions": {
      "type": "array",
      "minItems": 1,
      "maxItems": 100,
      "items": {
        "type": "object",
        "required": [
          "sheet",
          "range",
          "evidence_ids",
          "dependency_ids",
          "primary_id",
          "reason"
        ],
        "additionalProperties": false,
        "properties": {
          "sheet": {
            "type": "string",
            "enum": [
              "<SOURCE_SHEETS>"
            ]
          },
          "range": {
            "type": "string"
          },
          "reason": {
            "type": "string"
          },
          "evidence_ids": {
            "type": "array",
            "maxItems": 100,
            "items": {
              "type": "string",
              "enum": [
                "<SOURCE_EVIDENCE_IDS>"
              ]
            }
          },
          "dependency_ids": {
            "type": "array",
            "maxItems": 100,
            "items": {
              "type": "string",
              "enum": [
                "<SOURCE_EVIDENCE_IDS>"
              ]
            }
          },
          "primary_id": {
            "type": "string",
            "enum": [
              "<PRIMARY_EVIDENCE_IDS>"
            ]
          }
        }
      }
    },
    "logical_documents": {
      "type": "array",
      "maxItems": 100,
      "items": {
        "type": "object",
        "required": [
          "document_id",
          "fragments"
        ],
        "additionalProperties": false,
        "properties": {
          "document_id": {
            "type": "string"
          },
          "fragments": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
              "type": "object",
              "required": [
                "sheet",
                "range"
              ],
              "additionalProperties": false,
              "properties": {
                "sheet": {
                  "type": "string"
                },
                "range": {
                  "type": "string"
                }
              }
            }
          }
        }
      }
    },
    "layout_references": {
      "type": "array",
      "maxItems": 100,
      "items": {
        "type": "object",
        "required": [
          "sheet",
          "range"
        ],
        "additionalProperties": false,
        "properties": {
          "sheet": {
            "type": "string"
          },
          "range": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## 二阶段分组 user 消息结构

`output_schema` 是下文结构；`source_sha256` 绑定原件；`fragments` 来自前一阶段模型识别并经程序验证的范围，每项包括 `sheet`、`range`、模型给出的 `reason` 和程序分配的 `region_id`；`cells` 是程序从已读原始单元格选取的片段首尾和已引用证据，包含 `sheet`、`cell`、`value`、`kind`、`evidence_id`。分组前要求原始单元格覆盖完整。分组模型看到先前模型片段，并非每次只看全表原始正文。

## 分组输出 JSON Schema（动态枚举以占位符表示）

```json
{
  "type": "object",
  "required": [
    "groups"
  ],
  "additionalProperties": false,
  "properties": {
    "groups": {
      "type": "array",
      "maxItems": 100,
      "items": {
        "type": "object",
        "required": [
          "document_id",
          "fragment_ids",
          "evidence_ids",
          "reason"
        ],
        "additionalProperties": false,
        "properties": {
          "document_id": {
            "type": "string"
          },
          "fragment_ids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
              "type": "string",
              "enum": [
                "<MODEL_FRAGMENT_IDS>"
              ]
            }
          },
          "evidence_ids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
              "type": "string",
              "enum": [
                "<SOURCE_EVIDENCE_IDS>"
              ]
            }
          },
          "reason": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## 非自动兼容路径：实际使用的完整英文 system 文本

Identify physical fragments and group them into logical documents using only the supplied source cells and structure. Do not assume a document count or infer a business boundary from a transport batch or sheet boundary. Leave uncertain fragments ungrouped. Do not use unread content as evidence. Keep merged cells intact; every evidence coordinate MUST be inside its region and on the same sheet. External context belongs in dependencies. A repeated table header is an observation, not proof of continuation or a business category. Treat structural observations, not proof, as context only. Return exactly one JSON object matching output_schema, without extra fields.

### 中文翻译

仅根据提供的源单元格和结构识别物理片段并分组成逻辑单据。不要假定单据数量，也不要从传输批次或工作表边界推断业务边界。将不确定的片段保持为未分组。不要把未读取内容用作证据。保持合并单元格完整；每个证据坐标必须位于区域内且属于同一工作表。外部上下文应放在依赖项中。重复表头只是观察结果，不构成续页或业务类别的证明。把结构观察仅作为上下文，而不是证明。严格返回一个符合 output_schema 的 JSON 对象，不要添加额外字段。

注意：非自动兼容路径使用旧输出结构中的 labels 等字段及旧分类校验，不等同自动路径的编号结构；用户界面当前自动链使用 auto_group=true。

## 被替换的旧中间 system 文本（仅构造、发送前被覆盖）

Identify business document regions. Return exactly one JSON object matching output_schema, no extra fields. physical_regions are geometric fragments, not document counts. logical_documents group physical fragments only when supported; A supported standalone fragment is also a logical document with one fragment. Use distinct document_id values and leave uncertain fragments ungrouped. Do not provide a document count; software calculates it. layout_references contain only exact merged ranges from sheets.merged, including blank anchors; they are not semantic evidence. Evidence and dependencies are objects with sheet and cell fields; cell MUST be a bare coordinate like A1, never append a value or explanation. Structure coordinates are only an index, not evidence: classify only from cell values actually sent. For each region, every evidence coordinate MUST be inside that region and on the same sheet; external headings, shared legends and context belong ONLY in dependencies, never in evidence. Do not split merged cells or overlap regions. A repeated table header can be a continuation of the preceding document; it is not by itself evidence of a new document or different business category. Each non-unknown label needs positive category-specific evidence within the region. Generic item, quantity, price and amount headers alone do not establish a purchase order or other category. Each request may contain only part of a workbook; do not assume cells outside this batch were read. Cells marked context_only are repeated context, not part of this batch's primary consecutive rows; use them as dependencies where relevant and do not create a new document solely from them. Every physical region must contain a primary cell from this batch; do not propose regions solely from repeated context or unread rows. Use primary cells as evidence, not context_only cells. For each region, choose at most 20 concise evidence cells and at most 20 dependencies; do not list every cell. If evidence is insufficient or the relevant cells were not sent, use unknown; do not guess. Use relationship_context as observations, not proof: adjacency, identical or shifted headers, titles and shared notes may suggest continuation but may also occur in different documents. For a category change, cite category-specific support from sent cells inside the new region; otherwise use unknown and explain missing context. External parent titles or shared notes can be dependencies, never inside-region evidence. Dependencies may reference sent shared context. Do not infer database targets.

### 中文翻译

识别业务单据区域。严格返回一个符合 output_schema 的 JSON 对象，不要额外字段。physical_regions 是几何片段，不是单据数量；logical_documents 只在有依据时将物理片段分组。有依据的独立片段也可作为只有一个片段的逻辑单据。使用不同 document_id，对不确定的片段不分组。不要提供单据数量，软件会计算。layout_references 只能包含 sheets.merged 中的精确合并区域，包括空白锚点；它们不是语义证据。证据和依赖是包含 sheet 与 cell 的对象；cell 必须是 A1 形式的纯坐标，不得附加值或说明。结构坐标只是索引而不是证据：只能根据实际发送的单元格值分类。每个区域的每个证据坐标必须在该区域内且位于同一表；外部标题、共享图例与上下文只能放入依赖，不能放入证据。不要切断合并格或让区域重叠。重复表头可能是前一单据的续页；单独出现不代表新单据或不同业务类别。每个非 unknown 标签都需要区域内对应类别的正面证据。一般的项目、数量、价格和金额表头不足以证明采购订单或其他类别。每次请求可能只含工作簿一部分；不要假定本批之外的单元格已读。标记 context_only 的单元格是重复上下文，不属于本批主体连续行；相关时将其用作依赖，不能仅凭它们新建单据。每个物理区域必须包含本批的主体单元格；不要仅根据重复上下文或未读行提出区域。使用主体单元格作为证据，不使用 context_only 单元格。每个区域最多选择 20 个简洁证据单元格和 20 个依赖，不要列出每个格。证据不足或相关格未发送时使用 unknown，不要猜测。将 relationship_context 当作观察而非证明：相邻、相同或错位的表头、标题和共享备注可能提示续页，也可能出现在不同单据。类别变化时引用新区域内已发送的类别特定依据，否则使用 unknown 并说明缺失上下文。外部上级标题或共享备注可作依赖，不能作为区域内证据。依赖可以引用已发送的共享上下文。不要推断数据库目标。

## 版本和历史边界

识别提示 SHA-256：fd3c4a833f821b8ffbdc77dbd35557e8eeda9059c7fee59c4a6960bac5ac308e；分组提示 SHA-256：440a63ab70be709c7825a4e6374ef3c1f3e52687a3e8b4f3f5927235459ee22e。模板哈希分别为 e2e1ceb650586cdc2954e2e622e6807a03a3fec251aa122dc17d1fdd6dc01b4a 和 f0f500cbbf7f3925cae7f6885e51a46c92cb4069a8ded998c2724fdc4ba5f379。
当前识别文本与销售、材料第二轮实际发送的文本相同；那一轮是在看到首轮证据数量错误后加入通用数量说明，不能称为完全未见样本的首轮泛化。当前分组文本无已验证的真实发送记录。生产单无提示实测使用的是更早文本，其实际请求和输出另存；本说明不是生产单那次请求的原始记录。
本说明只覆盖此次 Excel 分类/分组链的提示，不包含应用其他功能已有的清理或改写提示，也不包含任何助手内部指令、认证头或密钥。
