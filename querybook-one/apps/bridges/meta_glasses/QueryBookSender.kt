// Ray-Ban Meta (Gen 2) / Meta Ray-Ban Display → QueryBook, from an Android companion app.
//
// The glasses' camera and microphone reach your app through Meta's Wearables Device Access Toolkit
// (wearables.developer.meta.com). Follow Meta's "Integration overview" to open a session and receive camera frames
// and audio; then analyse them ON THE PHONE (e.g. ML Kit object detection, Android SpeechRecognizer) and send only
// the results to QueryBook with this class. Pictures and sound never leave the phone unless you call upload().
//
//     val qb = QueryBookSender("http://192.168.1.20:9101", "qbd_...")
//     qb.detection("cup", 0.91)          // from your on-phone detector
//     qb.transcript("the meeting starts at ten", "en")
//     qb.flush()                          // also called automatically every 2 s by your timer
//
// The device needs 'people' (and, if you send places, 'location') consent in QueryBook. Template: build and test it
// with your toolkit version — the Meta session code is deliberately left to Meta's current documentation.
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class QueryBookSender(private val base: String, private val key: String) {
    private val buffer = mutableListOf<JSONObject>()

    private fun add(kind: String, data: JSONObject) = synchronized(buffer) {
        buffer.add(JSONObject().put("kind", kind).put("t", System.currentTimeMillis() / 1000.0).put("data", data))
    }

    fun detection(label: String, confidence: Double) = add("detection", JSONObject().put("label", label).put("confidence", confidence))
    fun transcript(text: String, lang: String? = null) = add("transcript", JSONObject().put("text", text).apply { if (lang != null) put("lang", lang) })
    fun location(lat: Double, lon: Double, accuracyM: Double) = add("location", JSONObject().put("lat", lat).put("lon", lon).put("accuracy_m", accuracyM))
    fun note(text: String) = add("note", JSONObject().put("text", text))

    fun flush() {
        val events = synchronized(buffer) { val e = JSONArray(buffer); buffer.clear(); e }
        if (events.length() == 0) return
        thread {
            val c = URL("$base/api/devices/ingest").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.setRequestProperty("Authorization", "Bearer $key")
            c.outputStream.use { it.write(JSONObject().put("events", events).toString().toByteArray()) }
            if (c.responseCode != 200) android.util.Log.w("QueryBook", "send failed: ${c.responseCode}")
            c.disconnect()
        }
    }
}
