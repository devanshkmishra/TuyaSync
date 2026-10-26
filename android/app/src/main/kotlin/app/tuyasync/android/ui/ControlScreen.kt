package app.tuyasync.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconToggleButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.tuyasync.android.LightViewModel
import app.tuyasync.core.ConnectionState
import app.tuyasync.core.Ds22000
import app.tuyasync.core.Hsv
import app.tuyasync.core.LightProfile
import app.tuyasync.core.LightState
import app.tuyasync.core.WorkMode
import kotlin.math.roundToInt

private val Swatches = listOf(0, 30, 55, 120, 180, 220, 270, 320)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ControlScreen(viewModel: LightViewModel, profile: LightProfile, onShowDetails: () -> Unit) {
    val connection by viewModel.connection.collectAsStateWithLifecycle()
    val light by viewModel.light.collectAsStateWithLifecycle()
    var menuOpen by rememberSaveable { mutableStateOf(false) }
    var confirmForget by rememberSaveable { mutableStateOf(false) }
    val connected = connection is ConnectionState.Connected

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(profile.name)
                        Text(connection.label(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                actions = {
                    IconButton(onClick = { menuOpen = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "More") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        DropdownMenuItem(text = { Text("Device details") }, onClick = { menuOpen = false; onShowDetails() })
                        DropdownMenuItem(text = { Text("Reconnect") }, onClick = { menuOpen = false; viewModel.retry() })
                        DropdownMenuItem(text = { Text("Remove this light") }, onClick = { menuOpen = false; confirmForget = true })
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            ConnectionBanner(connection, onRetry = viewModel::retry, onSetUpAgain = { confirmForget = true })
            PowerButton(light, enabled = connected, onToggle = viewModel::setPower)

            val controlsEnabled = connected && light.on
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                listOf(WorkMode.WHITE to "White", WorkMode.COLOUR to "Colour").forEachIndexed { index, (mode, label) ->
                    SegmentedButton(
                        selected = light.mode == mode,
                        onClick = { viewModel.setMode(mode) },
                        enabled = controlsEnabled,
                        shape = SegmentedButtonDefaults.itemShape(index, 2),
                    ) { Text(label) }
                }
            }
            when (light.mode) {
                WorkMode.SCENE, WorkMode.MUSIC -> Text(
                    "The light is running a ${if (light.mode == WorkMode.SCENE) "scene" else "music mode"}. Pick White or Colour to take over.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                WorkMode.COLOUR -> ColourControls(light, controlsEnabled, viewModel::setColour)
                else -> WhiteControls(light, controlsEnabled, viewModel::setWhite)
            }
        }
    }

    if (confirmForget) {
        AlertDialog(
            onDismissRequest = { confirmForget = false },
            title = { Text("Remove ${profile.name}?") },
            text = { Text("This deletes the saved Local Key from this phone. The light itself is not changed.") },
            confirmButton = { TextButton(onClick = { confirmForget = false; viewModel.forget() }) { Text("Remove") } },
            dismissButton = { TextButton(onClick = { confirmForget = false }) { Text("Cancel") } },
        )
    }
}

private fun ConnectionState.label(): String = when (this) {
    ConnectionState.Connected -> "Connected on Wi-Fi"
    ConnectionState.Connecting -> "Connecting…"
    ConnectionState.Disconnected -> "Not connected"
    is ConnectionState.Failed -> reason
}

@Composable
private fun ConnectionBanner(connection: ConnectionState, onRetry: () -> Unit, onSetUpAgain: () -> Unit) {
    val failure = connection as? ConnectionState.Failed ?: return
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (failure.keyRejected) {
                Text("The light didn't accept the Local Key.", style = MaterialTheme.typography.titleSmall)
                Text(
                    "This happens if the light was removed and re-added in Smart Life, which gives it a new key. " +
                        "Set it up again with the new key.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = onRetry) { Text("Try again") }
                    TextButton(onClick = onSetUpAgain) { Text("Set up again") }
                }
            } else {
                Text("Can't reach the light: ${failure.reason}", style = MaterialTheme.typography.titleSmall)
                Text(
                    "Check that the phone is on the same Wi-Fi as the light and the light has power. Retrying automatically.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                TextButton(onClick = onRetry) { Text("Retry now") }
            }
        }
    }
}

@Composable
private fun PowerButton(light: LightState, enabled: Boolean, onToggle: (Boolean) -> Unit) {
    val glow = when {
        !light.on -> MaterialTheme.colorScheme.surfaceVariant
        light.mode == WorkMode.COLOUR -> light.colour.toColor()
        else -> lerpWhite(light.colourTemp)
    }
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        FilledIconToggleButton(
            checked = light.on,
            onCheckedChange = onToggle,
            enabled = enabled,
            modifier = Modifier.size(132.dp).border(6.dp, glow, CircleShape),
            colors = IconButtonDefaults.filledIconToggleButtonColors(
                checkedContainerColor = MaterialTheme.colorScheme.primary,
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Icon(Icons.Filled.PowerSettingsNew, contentDescription = if (light.on) "Turn off" else "Turn on", modifier = Modifier.size(56.dp))
        }
    }
}

private fun lerpWhite(temp: Int): Color {
    val t = temp / 1000f
    return Color(
        red = WarmWhite.red + (CoolWhite.red - WarmWhite.red) * t,
        green = WarmWhite.green + (CoolWhite.green - WarmWhite.green) * t,
        blue = WarmWhite.blue + (CoolWhite.blue - WarmWhite.blue) * t,
    )
}

@Composable
private fun WhiteControls(light: LightState, enabled: Boolean, onChange: (Int, Int) -> Unit) {
    Column {
        LevelSlider(
            "Brightness", "${Ds22000.percent(light.brightness)}%", light.brightness.toFloat(),
            Ds22000.MIN_BRIGHTNESS.toFloat()..Ds22000.MAX_LEVEL.toFloat(),
            Brush.horizontalGradient(listOf(Color(0xFF3A3A3A), Color.White)), enabled,
        ) { onChange(it.roundToInt(), light.colourTemp) }
        LevelSlider(
            "Warm to cool", "${Ds22000.percent(light.colourTemp)}%", light.colourTemp.toFloat(), 0f..1000f,
            Brush.horizontalGradient(listOf(WarmWhite, Color.White, CoolWhite)), enabled,
        ) { onChange(light.brightness, it.roundToInt()) }
    }
}

@Composable
private fun ColourControls(light: LightState, enabled: Boolean, onChange: (Hsv) -> Unit) {
    val colour = light.colour
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Swatches.forEach { hue ->
                val selected = colour.hue == hue && colour.saturation == 1000
                Box(
                    Modifier.size(34.dp)
                        .background(Color.hsv(hue.toFloat(), 1f, 1f), CircleShape)
                        .border(if (selected) 3.dp else 0.dp, MaterialTheme.colorScheme.onSurface, CircleShape)
                        .clickable(enabled = enabled) { onChange(colour.copy(hue = hue, saturation = 1000)) },
                )
            }
        }
        LevelSlider("Colour", "${colour.hue}°", colour.hue.toFloat(), 0f..360f, hueBrush(), enabled) {
            onChange(colour.copy(hue = it.roundToInt()))
        }
        LevelSlider(
            "Saturation", "${Ds22000.percent(colour.saturation)}%", colour.saturation.toFloat(), 0f..1000f,
            Brush.horizontalGradient(listOf(Color.White, colour.copy(saturation = 1000).toColor())), enabled,
        ) { onChange(colour.copy(saturation = it.roundToInt())) }
        LevelSlider(
            "Brightness", "${Ds22000.percent(colour.value)}%", colour.value.toFloat(),
            Ds22000.MIN_BRIGHTNESS.toFloat()..Ds22000.MAX_LEVEL.toFloat(),
            Brush.horizontalGradient(listOf(Color(0xFF202020), colour.toColor())), enabled,
        ) { onChange(colour.copy(value = it.roundToInt())) }
    }
}
