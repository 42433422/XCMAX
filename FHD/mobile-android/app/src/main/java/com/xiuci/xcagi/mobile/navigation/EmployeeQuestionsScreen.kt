package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.outlined.QuestionAnswer
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.xiuci.xcagi.mobile.core.model.EmployeePendingQuestion
import com.xiuci.xcagi.mobile.ui.AppViewModel
import kotlinx.coroutines.launch

/**
 * 员工任务中心：Phase-D 主动提问列表 + 老板回答。
 *
 * 显示员工（如 llm-ops-engineer）通过 cognition 输出 requires_human=true 时
 * 写入 PendingHumanQuestion 表的问题，老板可以一条条点开回答。
 *
 * 入口：员工档案页的"问他/她的待回答问题"按钮，或工作 Tab 的"员工任务中心"。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EmployeeQuestionsScreen(
    vm: AppViewModel,
    employeeId: String?,  // null 表示拉全部员工
    onBack: () -> Unit,
) {
    val questions by vm.employeeQuestions.collectAsState()
    val loading by vm.employeeQuestionsLoading.collectAsState()
    val error by vm.employeeQuestionsError.collectAsState()
    val scope = rememberCoroutineScope()

    // 进入页面拉一次
    LaunchedEffect(employeeId) {
        vm.loadEmployeePendingQuestions(includeHistory = false, employeeId = employeeId)
    }
    // 离开页面清状态
    // （不用 DisposableEffect — popBackStack 时 LaunchedEffect 自动清理，状态保留反而能恢复滚动位置）

    var answeringId by remember { mutableStateOf<Int?>(null) }
    var answerText by remember { mutableStateOf("") }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        if (employeeId.isNullOrBlank()) "员工任务中心"
                        else "$employeeId 的提问"
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = {
                        scope.launch {
                            vm.loadEmployeePendingQuestions(
                                includeHistory = false,
                                employeeId = employeeId,
                            )
                        }
                    }) {
                        Icon(Icons.Outlined.QuestionAnswer, contentDescription = "刷新")
                    }
                },
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            when {
                loading && questions.isEmpty() -> {
                    CircularProgressIndicator(
                        modifier = Modifier.align(Alignment.Center)
                    )
                }
                error.isNotBlank() && questions.isEmpty() -> {
                    Column(
                        modifier = Modifier.align(Alignment.Center).padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            "拉不到员工提问：$error",
                            color = MaterialTheme.colorScheme.error,
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        )
                        Spacer(Modifier.height(12.dp))
                        Button(onClick = {
                            scope.launch {
                                vm.loadEmployeePendingQuestions(
                                    includeHistory = false,
                                    employeeId = employeeId,
                                )
                            }
                        }) { Text("重试") }
                    }
                }
                questions.isEmpty() -> {
                    Column(
                        modifier = Modifier.align(Alignment.Center).padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Icon(
                            Icons.Outlined.QuestionAnswer,
                            contentDescription = null,
                            modifier = Modifier.size(48.dp),
                            tint = MaterialTheme.colorScheme.outline,
                        )
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "暂无员工主动提问",
                            color = MaterialTheme.colorScheme.outline,
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "员工遇到需要老板决策的事会主动在这里问你",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
                else -> {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(12.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(questions, key = { it.id }) { q ->
                            QuestionCard(
                                question = q,
                                isAnswering = answeringId == q.id,
                                answerText = answerText,
                                onAnswerTextChange = { answerText = it },
                                onStartAnswer = {
                                    answeringId = q.id
                                    answerText = ""
                                },
                                onCancelAnswer = {
                                    answeringId = null
                                    answerText = ""
                                },
                                onSubmitAnswer = {
                                    scope.launch {
                                        val r = vm.answerEmployeePendingQuestion(q.id, answerText)
                                        if (r.isSuccess) {
                                            answeringId = null
                                            answerText = ""
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun QuestionCard(
    question: EmployeePendingQuestion,
    isAnswering: Boolean,
    answerText: String,
    onAnswerTextChange: (String) -> Unit,
    onStartAnswer: () -> Unit,
    onCancelAnswer: () -> Unit,
    onSubmitAnswer: () -> Unit,
) {
    val isPending = question.status == "pending"
    val cardColor = if (isPending) {
        MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.4f)
    } else {
        MaterialTheme.colorScheme.surface
    }
    val statusText = when (question.status) {
        "pending" -> "待回答"
        "answered" -> "已回答"
        "expired" -> "超时未答"
        else -> question.status
    }
    val statusColor = when (question.status) {
        "pending" -> Color(0xFFE65100)  // 橙色，要处理
        "answered" -> Color(0xFF2E7D32) // 绿色，已搞定
        "expired" -> Color(0xFF9E9E9E)  // 灰色，过期
        else -> MaterialTheme.colorScheme.outline
    }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = cardColor,
        tonalElevation = 1.dp,
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            // 第 1 行：员工 ID + 状态
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "@${question.employee_id}",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.primary,
                )
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = statusColor.copy(alpha = 0.12f),
                ) {
                    Text(
                        text = statusText,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                        fontSize = 11.sp,
                        color = statusColor,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
            Spacer(Modifier.height(6.dp))

            // 第 2 行：原始任务（小字、灰）
            if (question.task.isNotBlank()) {
                Text(
                    text = "原任务：${question.task}",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.outline,
                    maxLines = 2,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(6.dp))
            }

            // 第 3 行：员工的问题（主要内容）
            Surface(
                shape = RoundedCornerShape(8.dp),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
            ) {
                Text(
                    text = question.question,
                    modifier = Modifier.padding(10.dp),
                    fontSize = 14.sp,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }

            // 第 4 行：已答的内容（如果有）
            if (question.status == "answered" && question.answer.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = "你之前的回答：${question.answer}",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.outline,
                )
            }

            // 第 5 行：时间
            Spacer(Modifier.height(6.dp))
            Text(
                text = "提问时间：${question.asked_at}",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.outline,
            )

            // 第 6 行：回答框 / 按钮
            if (isPending) {
                if (isAnswering) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = answerText,
                        onValueChange = onAnswerTextChange,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("你的回答") },
                        minLines = 2,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
                    )
                    Spacer(Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End,
                    ) {
                        TextButton(onClick = onCancelAnswer) { Text("取消") }
                        Spacer(Modifier.size(8.dp))
                        Button(
                            onClick = onSubmitAnswer,
                            enabled = answerText.isNotBlank(),
                        ) { Text("发送回答") }
                    }
                } else {
                    Spacer(Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End,
                    ) {
                        Button(onClick = onStartAnswer) { Text("回答") }
                    }
                }
            }
        }
    }
}
