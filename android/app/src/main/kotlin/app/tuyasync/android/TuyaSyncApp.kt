package app.tuyasync.android

import android.app.Application

class TuyaSyncApp : Application() {
    val repository: LightRepository by lazy { LightRepository(ProfileStore(this), LanDiscovery(this)) }
}
