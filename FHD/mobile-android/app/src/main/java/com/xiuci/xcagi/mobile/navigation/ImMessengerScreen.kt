package com.xiuci.xcagi.mobile.navigation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import kotlinx.coroutines.flow.collectLatest
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xiuci.xcagi.mobile.ui.AppViewModel
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ImMessengerScreen(
    vm: AppViewModel,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var peerIdText by remember { mutableStateOf("2") }
    var conversationId by remember { mutableStateOf<Int?>(null) }
    var draft by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val messages = remember { mutableStateListOf<Map<String, Any?>>() }

    fun refreshMessages(cid: Int) {
        scope.launch {
            vm.imListMessages(cid)
                .onSuccess { body ->
                    @Suppress("UNCHECKED_CAST")
                    val list = body["messages"] as? List<Map<String, Any?>> ?: emptyList()
                    messages.clear()
                    messages.addAll(list)
                }
                .onFailure { error = it.message }
        }
    }

    DisposableEffect(Unit) {
        vm.connectImWebSocket()
        onDispose { vm.disconnectImWebSocket() }
    }

    LaunchedEffect(conversationId) {
        val cid = conversationId ?: return@LaunchedEffect
        refreshMessages(cid)
    }

    LaunchedEffect(conversationId) {
        val cid = conversationId ?: return@LaunchedEffect
        vm.imWsEvents.collectLatest { event ->
            if (event.optString("type") != "message") return@collectLatest
            if (event.optInt("conversation_id") != cid) return@collectLatest
            val msg = event.optJSONObject("message") ?: return@collectLatest
            val map = buildMap<String, Any?> {
                msg.keys().forEach { k -> put(k, msg.opt(k)) }
            }
            if (messages.none { (it["id"] as? Number)?.toLong() == (map["id"] as? Number)?.toLong() }) {
                messages.add(map)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("IM 消息") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { pad ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(pad)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (conversationId == null) {
                OutlinedTextField(
                    value = peerIdText,
                    onValueChange = { peerIdText = it },
                    label = { Text("对方用户 ID") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = {
                        val peer = peerIdText.toIntOrNull() ?: return@Button
                        scope.launch {
                            vm.imOpenDirect(peer)
                                .onSuccess { body ->
                                    @Suppress("UNCHECKED_CAST")
                                    val conv = body["conversation"] as? Map<String, Any?>
                                    conversationId = (conv?.get("id") as? Number)?.toInt()
                                    error = null
                                }
                                .onFailure { error = it.message }
                        }
                    },
                ) { Text("打开会话") }
            } else {
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(messages) { m ->
                        Text(
                            text = "${m["sender_user_id"]}: ${m["body"]}",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    label = { Text("消息") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = {
                        val cid = conversationId ?: return@Button
                        val text = draft.trim()
                        if (text.isEmpty()) return@Button
                        scope.launch {
                            vm.imSendMessage(cid, text)
                                .onSuccess {
                                    draft = ""
                                    refreshMessages(cid)
                                }
                                .onFailure { error = it.message }
                        }
                    },
                ) { Text("发送") }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
}
