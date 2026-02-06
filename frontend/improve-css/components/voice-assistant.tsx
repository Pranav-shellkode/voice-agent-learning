"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { Mic, MicOff, Send, Trash2, Wifi, WifiOff, MessageSquare, Volume2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface Message {
  id: string
  text: string
  sender: "user" | "assistant"
}

export function VoiceAssistant() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      text: "Hello! I'm your helpdesk assistant. You can type or speak to me!",
      sender: "assistant",
    },
  ])
  const [inputValue, setInputValue] = useState("")
  const [isConnected, setIsConnected] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")
  const [mode, setMode] = useState<"text" | "voice">("text")

  const wsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const conversationHistoryRef = useRef<unknown[]>([])
  const chatContainerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
    }
  }, [messages])

  const addMessage = useCallback((text: string, sender: "user" | "assistant") => {
    setMessages((prev) => [...prev, { id: Date.now().toString(), text, sender }])
  }, [])

  const playAudio = async (hexString: string) => {
    try {
      const bytes = new Uint8Array(
        hexString.match(/.{1,2}/g)!.map((byte) => parseInt(byte, 16))
      )
      const blob = new Blob([bytes], { type: "audio/mpeg" })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      await audio.play()
      audio.onended = () => URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Error playing audio:", err)
    }
  }

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket("ws://127.0.0.1:8000/ws")

      ws.onopen = () => {
        setIsConnected(true)
        setError("")
      }

      ws.onmessage = async (event) => {
        const data = JSON.parse(event.data)

        if (data.type === "response") {
          if (data.user_text) {
            addMessage(data.user_text, "user")
          }
          addMessage(data.text, "assistant")
          conversationHistoryRef.current = data.conversation_history || conversationHistoryRef.current

          if (data.audio) {
            await playAudio(data.audio)
          }
          setIsLoading(false)
        } else if (data.type === "error") {
          setError(data.message)
          setIsLoading(false)
        }
      }

      ws.onerror = () => {
        setError("Connection error. Make sure the backend is running.")
      }

      ws.onclose = () => {
        setIsConnected(false)
      }

      wsRef.current = ws
    } catch (err) {
      setError("Failed to connect: " + (err as Error).message)
    }
  }, [addMessage])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.send(JSON.stringify({ type: "close" }))
      wsRef.current.close()
    }
  }, [])

  const toggleConnection = () => {
    if (isConnected) {
      disconnect()
    } else {
      connect()
    }
  }

  const sendMessage = () => {
    const text = inputValue.trim()
    if (!text) return
    if (!isConnected) {
      setError("Please connect to the server first")
      return
    }

    addMessage(text, "user")
    setInputValue("")
    setIsLoading(true)

    try {
      wsRef.current?.send(
        JSON.stringify({
          type: "text",
          data: text,
          conversation_history: conversationHistoryRef.current,
        })
      )
    } catch (err) {
      setError("Failed to send message: " + (err as Error).message)
      setIsLoading(false)
    }
  }

  const sendAudio = async (audioBlob: Blob) => {
    try {
      const arrayBuffer = await audioBlob.arrayBuffer()
      const base64Audio = btoa(
        new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), "")
      )

      wsRef.current?.send(JSON.stringify({ type: "audio_chunk", data: base64Audio }))
      wsRef.current?.send(
        JSON.stringify({
          type: "end_turn",
          conversation_history: conversationHistoryRef.current,
        })
      )
    } catch (err) {
      setError("Failed to send audio: " + (err as Error).message)
      setIsLoading(false)
    }
  }

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        audioChunksRef.current.push(event.data)
      }

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" })
        await sendAudio(audioBlob)
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorder.start()
      mediaRecorderRef.current = mediaRecorder
      setIsRecording(true)
    } catch (err) {
      setError("Microphone access denied: " + (err as Error).message)
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
      setIsLoading(true)
    }
  }

  const toggleRecording = () => {
    if (!isConnected) {
      setError("Please connect to the server first")
      return
    }
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const clearChat = () => {
    setMessages([
      {
        id: "1",
        text: "Hello! I'm your helpdesk assistant. You can type or speak to me!",
        sender: "assistant",
      },
    ])
    conversationHistoryRef.current = []
  }

  return (
    <div className="min-h-screen w-full bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center p-4 sm:p-6">
      {/* Animated background elements */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-cyan-500/10 rounded-full blur-3xl animate-pulse" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-teal-500/10 rounded-full blur-3xl animate-pulse delay-1000" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-900/5 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-lg">
        {/* Glow effect behind card */}
        <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/20 to-teal-500/20 rounded-3xl blur-xl opacity-50" />
        
        <div className="relative bg-slate-900/80 backdrop-blur-xl rounded-3xl border border-slate-700/50 shadow-2xl shadow-cyan-500/10 overflow-hidden">
          {/* Header */}
          <div className="relative bg-gradient-to-r from-slate-800 to-slate-900 px-6 py-8 text-center border-b border-slate-700/50">
            <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/5 to-teal-500/5" />
            <div className="relative">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan-500 to-teal-500 mb-4 shadow-lg shadow-cyan-500/25">
                <Volume2 className="w-7 h-7 text-white" />
              </div>
              <h1 className="text-2xl font-semibold text-white tracking-tight">
                Shellkode Helpdesk
              </h1>
              <div className="flex items-center justify-center gap-2 mt-3">
                <div className="relative">
                  <span
                    className={cn(
                      "block w-2.5 h-2.5 rounded-full transition-colors duration-300",
                      isConnected ? "bg-emerald-400" : "bg-red-400"
                    )}
                  />
                  {isConnected && (
                    <span className="absolute inset-0 w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping opacity-75" />
                  )}
                </div>
                <span className="text-sm text-slate-400">
                  {isConnected ? "Connected" : "Disconnected"}
                </span>
              </div>
            </div>
          </div>

          {/* Chat Container */}
          <div
            ref={chatContainerRef}
            className="h-80 overflow-y-auto p-5 space-y-4 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent"
          >
            {messages.map((message, index) => (
              <div
                key={message.id}
                className={cn(
                  "flex animate-in slide-in-from-bottom-2 fade-in duration-300",
                  message.sender === "user" ? "justify-end" : "justify-start"
                )}
                style={{ animationDelay: `${index * 50}ms` }}
              >
                <div
                  className={cn(
                    "max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed",
                    message.sender === "user"
                      ? "bg-gradient-to-r from-cyan-500 to-teal-500 text-white rounded-br-md shadow-lg shadow-cyan-500/20"
                      : "bg-slate-800/80 text-slate-200 rounded-bl-md border border-slate-700/50"
                  )}
                >
                  {message.text}
                </div>
              </div>
            ))}
            
            {isLoading && (
              <div className="flex justify-start animate-in fade-in duration-200">
                <div className="bg-slate-800/80 text-slate-400 px-4 py-3 rounded-2xl rounded-bl-md border border-slate-700/50">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 bg-cyan-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-2 h-2 bg-cyan-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-2 h-2 bg-cyan-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="p-5 border-t border-slate-700/50 bg-slate-900/50 space-y-4">
            {/* Mode Tabs */}
            <div className="flex gap-2 p-1 bg-slate-800/50 rounded-xl">
              <button
                onClick={() => setMode("text")}
                className={cn(
                  "flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-200",
                  mode === "text"
                    ? "bg-gradient-to-r from-cyan-500 to-teal-500 text-white shadow-lg shadow-cyan-500/25"
                    : "text-slate-400 hover:text-slate-300 hover:bg-slate-700/50"
                )}
              >
                <MessageSquare className="w-4 h-4" />
                Text
              </button>
              <button
                onClick={() => setMode("voice")}
                className={cn(
                  "flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg text-sm font-medium transition-all duration-200",
                  mode === "voice"
                    ? "bg-gradient-to-r from-cyan-500 to-teal-500 text-white shadow-lg shadow-cyan-500/25"
                    : "text-slate-400 hover:text-slate-300 hover:bg-slate-700/50"
                )}
              >
                <Mic className="w-4 h-4" />
                Voice
              </button>
            </div>

            {/* Text Mode */}
            {mode === "text" && (
              <div className="flex gap-3">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                  placeholder="Type your message..."
                  className="flex-1 bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50 transition-all duration-200"
                />
                <button
                  onClick={sendMessage}
                  disabled={isLoading || !inputValue.trim()}
                  className="bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-5 py-3 rounded-xl font-medium text-sm hover:shadow-lg hover:shadow-cyan-500/25 hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-none transition-all duration-200"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Voice Mode */}
            {mode === "voice" && (
              <div className="flex flex-col items-center gap-3 py-2">
                <button
                  onClick={toggleRecording}
                  disabled={isLoading}
                  className={cn(
                    "relative w-16 h-16 rounded-full flex items-center justify-center transition-all duration-300",
                    isRecording
                      ? "bg-red-500 shadow-lg shadow-red-500/40"
                      : "bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:-translate-y-1",
                    isLoading && "opacity-50 cursor-not-allowed"
                  )}
                >
                  {isRecording && (
                    <>
                      <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-30" />
                      <span className="absolute inset-[-8px] rounded-full border-2 border-red-400/50 animate-pulse" />
                    </>
                  )}
                  {isRecording ? (
                    <MicOff className="w-6 h-6 text-white relative z-10" />
                  ) : (
                    <Mic className="w-6 h-6 text-white relative z-10" />
                  )}
                </button>
                <p className="text-sm text-slate-400">
                  {isRecording ? "Recording... Click to stop" : isLoading ? "Processing audio..." : "Click to start recording"}
                </p>
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                onClick={toggleConnection}
                className={cn(
                  "flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 border",
                  isConnected
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20"
                    : "bg-slate-800/50 border-slate-700/50 text-slate-400 hover:bg-slate-700/50 hover:text-slate-300"
                )}
              >
                {isConnected ? (
                  <>
                    <WifiOff className="w-4 h-4" />
                    Disconnect
                  </>
                ) : (
                  <>
                    <Wifi className="w-4 h-4" />
                    Connect
                  </>
                )}
              </button>
              <button
                onClick={clearChat}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium bg-slate-800/50 border border-slate-700/50 text-slate-400 hover:bg-slate-700/50 hover:text-slate-300 transition-all duration-200"
              >
                <Trash2 className="w-4 h-4" />
                Clear Chat
              </button>
            </div>

            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="w-2 h-2 bg-red-400 rounded-full shrink-0" />
                {error}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
