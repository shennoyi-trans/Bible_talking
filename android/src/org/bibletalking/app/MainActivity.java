package org.bibletalking.app;

import android.app.Activity;
import android.os.Bundle;
import android.content.*;
import android.net.Uri;
import android.webkit.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

public final class MainActivity extends Activity {
    private static final String ORIGIN="https://appassets.androidplatform.net";
    private WebView web;
    private ValueCallback<Uri[]> chooser;
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private Encoder encoder;
    private volatile boolean destroyed=false;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        web=new WebView(this);setContentView(web);
        WebSettings settings=web.getSettings();
        settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        web.addJavascriptInterface(new Bridge(),"BibleTalkingNative");
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request) {
                Uri uri=request.getUrl();
                if(!"https".equals(uri.getScheme())||!"appassets.androidplatform.net".equals(uri.getHost()))
                    return blocked();
                String path=uri.getPath();
                if(path==null||path.contains(".."))return blocked();
                if(path.equals("/"))path="/index.html";
                String mime=path.endsWith(".js")?"text/javascript":path.endsWith(".css")?"text/css":
                    path.endsWith(".html")?"text/html":path.endsWith(".json")?"application/json":"application/octet-stream";
                try {
                    Map<String,String> headers=new HashMap<>();headers.put("Cache-Control","no-cache");
                    headers.put("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; worker-src 'self'; frame-src 'none'; object-src 'none'");
                    return new WebResourceResponse(mime,"UTF-8",200,"OK",headers,getAssets().open("web"+path));
                } catch(IOException e) { return blocked(); }
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) {
                // The native bridge is exposed only to our bundled application.
                return !request.getUrl().toString().equals(ORIGIN+"/");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params) {
                if(chooser!=null)chooser.onReceiveValue(null);chooser=callback;
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                try { startActivityForResult(intent,101); } catch(ActivityNotFoundException e) { chooser.onReceiveValue(null);chooser=null; }
                return true;
            }
        });
        web.loadUrl(ORIGIN+"/");
    }
    private static WebResourceResponse blocked() {
        return new WebResourceResponse("text/plain","UTF-8",404,"Not Found",null,new ByteArrayInputStream(new byte[0]));
    }
    private void reply(String id,Object data,String error) {
        if(destroyed)return;
        runOnUiThread(()-> { if(!destroyed)web.evaluateJavascript("window.__bibleNativeReply("+JSONObject.quote(id)+","+
            (data==null?"null":data.toString())+","+(error==null?"null":JSONObject.quote(error))+")",null); });
    }
    public final class Bridge {
        @JavascriptInterface public void encode(String id,String text) {
            if(text==null||text.length()>20000){reply(id,null,"文本过长，请分段处理。");return;}
            executor.execute(()-> {
                try {
                    if(encoder==null) {
                        File model=new File(getFilesDir(),"bge-small-zh-v1.5.onnx");
                        if(!model.exists()||model.length()!=94781076L) {
                            File temp=new File(getFilesDir(),"model.tmp");
                            try(InputStream input=getAssets().open("model.onnx")) { Files.copy(input,temp.toPath(),StandardCopyOption.REPLACE_EXISTING); }
                            Files.move(temp.toPath(),model.toPath(),StandardCopyOption.REPLACE_EXISTING);
                        }
                        encoder=new Encoder(model.getAbsolutePath(),getAssets().open("vocab.txt"));
                    }
                    JSONArray array=new JSONArray();for(float v:encoder.encode(text))array.put((double)v);reply(id,array,null);
                } catch(Exception e) { android.util.Log.e("Bible_talking","Embedding failed",e);reply(id,null,"本地模型未能完成检索，请重启应用后重试。"); }
            });
        }
        @JavascriptInterface public void copy(String text) {
            runOnUiThread(()->((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Bible_talking",text)));
        }
        @JavascriptInterface public void close() { runOnUiThread(()->finish()); }
    }
    @Override protected void onActivityResult(int request,int result,Intent intent) {
        super.onActivityResult(request,result,intent);
        if(request==101&&chooser!=null) { chooser.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,intent));chooser=null; }
    }
    @Override public void onBackPressed() { web.evaluateJavascript("window.dispatchEvent(new Event('bible-back'))",null); }
    @Override protected void onDestroy() {
        destroyed=true;if(chooser!=null)chooser.onReceiveValue(null);
        web.removeJavascriptInterface("BibleTalkingNative");web.destroy();
        executor.execute(()-> {try{if(encoder!=null)encoder.close();}catch(Exception ignored){}});executor.shutdown();
        super.onDestroy();
    }
}
