package app.tuyasync.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.tuyasync.android.LightViewModel
import app.tuyasync.core.Dp
import app.tuyasync.core.LightProfile

/** Every data point the light reports, so missing or extra features can be spotted. The Local Key is never shown. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeviceDetailsScreen(viewModel: LightViewModel, profile: LightProfile, onBack: () -> Unit) {
    val dps by viewModel.dps.collectAsStateWithLifecycle()
    val clipboard = LocalClipboardManager.current
    val rows = listOf("Name" to profile.name, "Device ID" to profile.deviceId, "IP address" to profile.ipAddress.ifBlank { "finding…" }, "Protocol" to profile.protocol)
    val points = dps.entries.sortedBy { it.key.toIntOrNull() ?: Int.MAX_VALUE }
    val report = (rows.map { "${it.first}: ${it.second}" } +
        points.map { "DP ${it.key} (${Dp.NAMES[it.key] ?: "unknown"}): ${it.value}" }).joinToString("\n")

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Device details") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") } },
                actions = {
                    IconButton(onClick = { viewModel.refresh() }) { Icon(Icons.Filled.Refresh, contentDescription = "Refresh") }
                    IconButton(onClick = { clipboard.setText(AnnotatedString(report)) }) { Icon(Icons.Filled.ContentCopy, contentDescription = "Copy report") }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            rows.forEach { (label, value) -> DetailRow(label, value) }
            HorizontalDivider()
            Text("Data points reported by the light", style = MaterialTheme.typography.titleMedium)
            if (points.isEmpty()) Text("None yet. Connect to the light, then tap refresh.")
            points.forEach { (dp, value) -> DetailRow("DP $dp · ${Dp.NAMES[dp] ?: "unknown"}", value.content) }
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodyMedium, fontFamily = FontFamily.Monospace, modifier = Modifier.weight(1f))
    }
}
