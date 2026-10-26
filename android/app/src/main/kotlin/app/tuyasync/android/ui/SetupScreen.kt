package app.tuyasync.android.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FileOpen
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.WifiFind
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.tuyasync.android.LightViewModel
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SetupScreen(viewModel: LightViewModel) {
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val message by viewModel.message.collectAsStateWithLifecycle()
    LaunchedEffect(message) {
        message?.let {
            snackbar.showSnackbar(it)
            viewModel.dismissMessage()
        }
    }

    val scanner = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { viewModel.importShareText(it) }
    }
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            val text = runCatching {
                context.contentResolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) }
            }.getOrNull()
            viewModel.importShareText(text.orEmpty())
        }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Add your light") }) },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "TuyaSync controls your light directly over Wi-Fi. It needs the light's Local Key once; " +
                    "after that, no Smart Life app or cloud account is involved.",
                style = MaterialTheme.typography.bodyMedium,
            )

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("From TuyaSync on your computer", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Open Light, choose Share to phone, and scan the code. You can also open an exported " +
                            ".tuyasync-profile.json file.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Button(
                        onClick = {
                            scanner.launch(
                                ScanOptions()
                                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                    .setPrompt("Scan the code shown by TuyaSync")
                                    .setBeepEnabled(false)
                                    .setOrientationLocked(false),
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Filled.QrCodeScanner, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Scan QR code")
                    }
                    OutlinedButton(onClick = { filePicker.launch(arrayOf("application/json", "text/plain", "*/*")) }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Filled.FileOpen, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Open profile file")
                    }
                }
            }

            ManualEntryCard(viewModel)
        }
    }
}

@Composable
private fun ManualEntryCard(viewModel: LightViewModel) {
    val nearby by viewModel.nearby.collectAsStateWithLifecycle()
    val scanning by viewModel.scanning.collectAsStateWithLifecycle()
    var name by rememberSaveable { mutableStateOf("My light") }
    var deviceId by rememberSaveable { mutableStateOf("") }
    var localKey by rememberSaveable { mutableStateOf("") }
    var ip by rememberSaveable { mutableStateOf("") }
    var protocol by rememberSaveable { mutableStateOf("3.5") }
    var showKey by rememberSaveable { mutableStateOf(false) }

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Enter the details yourself", style = MaterialTheme.typography.titleMedium)
            Text(
                "Find the light on this Wi-Fi to fill in its Device ID and address, then type the Local Key.",
                style = MaterialTheme.typography.bodyMedium,
            )
            OutlinedButton(onClick = viewModel::scanNearby, enabled = !scanning, modifier = Modifier.fillMaxWidth()) {
                if (scanning) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Filled.WifiFind, contentDescription = null)
                }
                Spacer(Modifier.width(8.dp))
                Text(if (scanning) "Listening for lights…" else "Find lights on this Wi-Fi")
            }
            if (!scanning && nearby.isEmpty()) {
                Text(
                    "Nothing found yet? Make sure the phone is on the same Wi-Fi as the light and the light is powered.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            nearby.forEach { device ->
                Row(
                    Modifier.fillMaxWidth().clickable {
                        deviceId = device.deviceId
                        ip = device.ip
                        protocol = device.version
                    }.padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(device.deviceId, style = MaterialTheme.typography.bodyLarge)
                        Text("${device.ip} · protocol ${device.version}", style = MaterialTheme.typography.bodySmall)
                    }
                    Text("Use", color = MaterialTheme.colorScheme.primary)
                }
                HorizontalDivider()
            }

            OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(deviceId, { deviceId = it.trim() }, label = { Text("Device ID") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(
                localKey, { localKey = it },
                label = { Text("Local Key (16 characters)") },
                singleLine = true,
                visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                trailingIcon = {
                    IconButton(onClick = { showKey = !showKey }) {
                        Icon(if (showKey) Icons.Filled.VisibilityOff else Icons.Filled.Visibility, contentDescription = "Show key")
                    }
                },
                supportingText = { Text("${localKey.length}/16") },
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                ip, { ip = it.trim() },
                label = { Text("IP address (optional)") },
                supportingText = { Text("Leave blank to find it automatically") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                protocol, { protocol = it.trim() },
                label = { Text("Protocol version") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(4.dp))
            Button(
                onClick = { viewModel.saveManual(name, deviceId, localKey, ip, protocol) },
                enabled = deviceId.isNotBlank() && localKey.length == 16,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Save and connect") }
        }
    }
}
