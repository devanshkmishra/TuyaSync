package app.tuyasync.android.ui

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.tuyasync.android.LightViewModel

@Composable
fun TuyaSyncRoot(viewModel: LightViewModel) {
    val profile by viewModel.profile.collectAsStateWithLifecycle()
    var showDetails by rememberSaveable { mutableStateOf(false) }
    val current = profile
    when {
        current == null -> SetupScreen(viewModel)
        showDetails -> {
            BackHandler { showDetails = false }
            DeviceDetailsScreen(viewModel, current, onBack = { showDetails = false })
        }
        else -> ControlScreen(viewModel, current, onShowDetails = { showDetails = true })
    }
}
