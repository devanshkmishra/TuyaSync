package app.tuyasync.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import app.tuyasync.android.ui.TuyaSyncRoot
import app.tuyasync.android.ui.TuyaSyncTheme

class MainActivity : ComponentActivity() {
    private val viewModel: LightViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            TuyaSyncTheme {
                TuyaSyncRoot(viewModel)
            }
        }
    }

    // Hold the connection only while the app is on screen, like Smart Life does.
    override fun onStart() {
        super.onStart()
        viewModel.start()
    }

    override fun onStop() {
        viewModel.stop()
        super.onStop()
    }
}
