package com.iflytek.astron.console.toolkit.websocket;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.iflytek.astron.console.toolkit.config.exception.CustomException;
import com.iflytek.astron.console.toolkit.config.properties.CommonConfig;
import com.iflytek.astron.console.toolkit.entity.spark.SparkApiProtocol;
import com.iflytek.astron.console.toolkit.mapper.ConfigInfoMapper;
import com.iflytek.astron.console.toolkit.tool.http.HttpAuthTool;
import com.iflytek.astron.console.toolkit.tool.spark.MessageBuilder;
import com.iflytek.astron.console.toolkit.util.OkHttpUtil;
import com.iflytek.astron.console.toolkit.util.SpringUtils;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import okio.ByteString;
import org.jetbrains.annotations.NotNull;
import org.springframework.http.HttpMethod;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/**
 * WebSocket handler for prompt enhancement feature.
 * <p>
 * This handler establishes a bridge between the client WebSocket and the Spark API WebSocket. It
 * manages connection creation, message forwarding, and error handling.
 * </p>
 *
 * <p>
 * <b>Responsibilities:</b>
 * </p>
 * <ul>
 * <li>Authenticate and connect to Spark API via signed WebSocket URL.</li>
 * <li>Forward user messages from the frontend to Spark API.</li>
 * <li>Relay Spark API responses back to the client WebSocket session.</li>
 * <li>Handle connection lifecycle events and clean up resources.</li>
 * </ul>
 *
 * @author
 * @since 2025/10/09
 */
@Slf4j
public class PromptEnhanceWebSocketHandler extends TextWebSocketHandler {

    /** Mapper for configuration information. */
    private final ConfigInfoMapper configInfoMapper = SpringUtils.getBean(ConfigInfoMapper.class);

    /** Common configuration bean. */
    private final CommonConfig commonConfig = SpringUtils.getBean(CommonConfig.class);

    /** Default Spark API WebSocket endpoint URL. */
    public static final String URL = "wss://spark-api.xf-yun.com/v3.5/chat";

    /** Map to hold WebSocket connections keyed by session ID. */
    private final Map<String, WebSocket> webSocketMap = new HashMap<>();

    /**
     * Called when a new WebSocket connection is established.
     * <p>
     * Creates a connection to the Spark API WebSocket with authentication and links it to the current
     * session.
     * </p>
     *
     * @param session the current {@link WebSocketSession}
     */
    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        // Authentication and encryption
        String signedSparkUrl = HttpAuthTool.assembleRequestUrl(
                URL, HttpMethod.GET.name(), commonConfig.getApiKey(), commonConfig.getApiSecret());
        Request request = new Request.Builder().url(signedSparkUrl).build();

        WebSocket webSocket = OkHttpUtil.getHttpClient().newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(@NotNull WebSocket webSocket, @NotNull Response response) {
                super.onOpen(webSocket, response);
                log.info("Spark API WebSocket connection established successfully.");
            }

            @Override
            public void onMessage(@NotNull WebSocket webSocket, @NotNull String text) {
                super.onMessage(webSocket, text);
                log.info("Received message from Spark API: {}", text);

                SparkApiProtocol responseDto = JSON.parseObject(text, SparkApiProtocol.class);
                if (responseDto.getHeader().getCode() != 0) {
                    try {
                        session.sendMessage(new TextMessage(text));
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                    throw new CustomException(text);
                }

                try {
                    session.sendMessage(new TextMessage(text));
                } catch (IOException e) {
                    throw new RuntimeException(e);
                }

                if (responseDto.getHeader().getStatus() == 2) {
                    try {
                        session.close();
                        webSocketMap.remove(session.getId());
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                }
            }

            @Override
            public void onMessage(@NotNull WebSocket webSocket, @NotNull ByteString bytes) {
                super.onMessage(webSocket, bytes);
                log.info("Received binary message from Spark API: {}", bytes);
            }

            @Override
            public void onClosing(@NotNull WebSocket webSocket, int code, @NotNull String reason) {
                super.onClosing(webSocket, code, reason);
                log.info("Spark API WebSocket is closing. Code: {}, Reason: [{}]", code, reason);
            }

            @Override
            public void onClosed(@NotNull WebSocket webSocket, int code, @NotNull String reason) {
                super.onClosed(webSocket, code, reason);
                log.info("Spark API WebSocket closed. Code: {}, Reason: [{}]", code, reason);
            }

            @Override
            public void onFailure(@NotNull WebSocket webSocket, @NotNull Throwable t, Response response) {
                super.onFailure(webSocket, t, response);
                log.error("Spark API WebSocket connection failed. Reason: {}", t.getMessage(), t);
            }
        });

        webSocketMap.put(session.getId(), webSocket);
    }

    /**
     * Handles messages received from the frontend client WebSocket.
     * <p>
     * Parses the received JSON, builds a Spark API message, and forwards it to the corresponding
     * WebSocket.
     * </p>
     *
     * @param session the current {@link WebSocketSession}
     * @param message the text message received from the client
     * @throws RuntimeException if message forwarding fails
     */
    @Override
    public void handleTextMessage(WebSocketSession session, TextMessage message) {
        String content = message.getPayload();
        JSONObject req = JSON.parseObject(content);
        String name = req.getString("name");
        String prompt = req.getString("prompt");

        String template = configInfoMapper.getByCategoryAndCode("TEMPLATE", "prompt-enhance").getValue();
        String question = template
                .replace("{assistant_name}", name)
                .replace("{assistant_description}", prompt);

        String msg = MessageBuilder.buildSparkApiRequest(question, commonConfig.getAppId());
        log.info("Sending message to Spark API: {}", msg);
        webSocketMap.get(session.getId()).send(msg);
    }

    /**
     * Handles transport-level errors during WebSocket communication.
     *
     * @param session the current {@link WebSocketSession}
     * @param exception the {@link Throwable} representing the transport error
     * @throws Exception if session closing fails
     */
    @Override
    public void handleTransportError(@NotNull WebSocketSession session, @NotNull Throwable exception) throws Exception {
        log.error("[session = {}] Transport error occurred: {}", session, exception.getMessage(), exception);
        session.close();
        webSocketMap.remove(session.getId());
    }

    /**
     * Called when a WebSocket connection is closed.
     * <p>
     * Performs cleanup by closing the session and removing the connection mapping.
     * </p>
     *
     * @param session the current {@link WebSocketSession}
     * @param closeStatus the {@link CloseStatus} indicating reason and code
     * @throws IOException if session closing fails
     */
    @Override
    public void afterConnectionClosed(@NotNull WebSocketSession session, CloseStatus closeStatus) throws IOException {
        log.info("[session = {}] Connection closed. Code: {}, Reason: {}", session, closeStatus.getCode(), closeStatus.getReason());
        if (closeStatus.getCode() == CloseStatus.NORMAL.getCode()) {
            log.info("Client disconnected normally.");
        } else {
            log.error("Client disconnected abnormally.");
        }
        session.close();
        webSocketMap.remove(session.getId());
    }
}
