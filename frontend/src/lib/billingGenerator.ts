interface BillingItem {
  service_name: string
  service_date: string
  outstanding: number
  payment_status: string
  description?: string
}

interface PaymentDetails {
  accountNumber: string
  bankName: string
  accountName: string
}

/**
 * Get current time in Africa/Lagos timezone and determine greeting
 */
function getGreetingForCurrentTime(): string {
  // Create a date formatter for Africa/Lagos timezone
  const lagosTime = new Date().toLocaleString('en-US', { timeZone: 'Africa/Lagos' })
  const date = new Date(lagosTime)
  const hour = date.getHours()
  
  // Determine greeting based on hour (Africa/Lagos time)
  if (hour >= 0 && hour < 12) {
    return 'Good morning'
  } else if (hour >= 12 && hour < 17) {
    return 'Good afternoon'
  } else {
    return 'Good evening'
  }
}

/**
 * Format date to verbose format like "Fri. 17th of April"
 */
function formatDateVerbose(dateStr: string): string {
  if (!dateStr) return ''
  
  const date = new Date(dateStr)
  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const monthNames = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
  ]
  
  const day = date.getDate()
  const dayName = dayNames[date.getDay()]
  const monthName = monthNames[date.getMonth()]
  
  // Add ordinal suffix
  let ordinal = 'th'
  if (day % 10 === 1 && day !== 11) ordinal = 'st'
  else if (day % 10 === 2 && day !== 12) ordinal = 'nd'
  else if (day % 10 === 3 && day !== 13) ordinal = 'rd'
  
  return `${dayName}. ${day}${ordinal} of ${monthName}`
}

/**
 * Format date to time format like "16:53"
 */
function formatTime(date: Date = new Date()): string {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/**
 * Apply bold italic formatting using mathematical alphanumeric symbols
 */
function applyBoldItalic(text: string): string {
  const boldItalicMap: { [key: string]: string } = {
    'A': '𝑨', 'B': '𝑩', 'C': '𝑪', 'D': '𝑫', 'E': '𝑬', 'F': '𝑭', 'G': '𝑮', 'H': '𝑯', 'I': '𝑰', 'J': '𝑱',
    'K': '𝑲', 'L': '𝑳', 'M': '𝑴', 'N': '𝑵', 'O': '𝑶', 'P': '𝑷', 'Q': '𝑸', 'R': '𝑹', 'S': '𝑺', 'T': '𝑻',
    'U': '𝑼', 'V': '𝑽', 'W': '𝑾', 'X': '𝑿', 'Y': '𝒀', 'Z': '𝒁',
    'a': '𝒂', 'b': '𝒃', 'c': '𝒄', 'd': '𝒅', 'e': '𝒆', 'f': '𝒇', 'g': '𝒈', 'h': '𝒉', 'i': '𝒊', 'j': '𝒋',
    'k': '𝒌', 'l': '𝒍', 'm': '𝒎', 'n': '𝒏', 'o': '𝒐', 'p': '𝒑', 'q': '𝒒', 'r': '𝒓', 's': '𝒔', 't': '𝒕',
    'u': '𝒖', 'v': '𝒗', 'w': '𝒘', 'x': '𝒙', 'y': '𝒚', 'z': '𝒛',
    '0': '𝟎', '1': '𝟏', '2': '𝟐', '3': '𝟑', '4': '𝟒', '5': '𝟓', '6': '𝟔', '7': '𝟕', '8': '𝟖', '9': '𝟗',
  }
  
  return text.split('').map(char => boldItalicMap[char] || char).join('')
}

/**
 * Generate the formatted billing text
 */
export function generateBillingText(
  clientName: string,
  items: BillingItem[],
  totalOutstanding: number,
  paymentDetails: PaymentDetails,
  currency: string = 'NGN'
): string {
  const now = new Date()
  const dateGenerated = formatDateVerbose(now.toISOString().slice(0, 10))
  const timeGenerated = formatTime(now)
  
  // Greeting - dynamically determined based on current time in Africa/Lagos
  const greeting = getGreetingForCurrentTime()
  let text = applyBoldItalic(greeting) + ' ' + applyBoldItalic(clientName.toUpperCase()) + ', ' + applyBoldItalic('I trust you\'re doing well.')
  text += '\n' + applyBoldItalic('Here is a quick summary of your outstanding bill for your review:')
  text += '\n\n'
  
  // Header
  text += clientName.toUpperCase() + '\n'
  text += `Generated: ${dateGenerated} at ${timeGenerated}\n`
  text += `*Total Outstanding: ${currency} ${formatCurrencyNoSymbol(totalOutstanding)}*\n\n`
  
  // Breakdown
  text += 'Breakdown (' + items.length + ' item(s)):\n\n'
  
  // Items
  items.forEach((item, index) => {
    text += (index + 1) + '. ' + applyBoldItalic(item.service_name.toUpperCase()) + '\n'
    text += `   Date: ${formatDateVerbose(item.service_date)}\n`
    text += `   Balance: ${currency} ${formatCurrencyNoSymbol(item.outstanding)}\n`
    text += `   Status: ${item.payment_status}\n\n`
  })
  
  // Payment details
  text += 'Payment Details:\n'
  text += paymentDetails.accountNumber + '\n'
  text += paymentDetails.bankName + '\n'
  text += paymentDetails.accountName + '\n\n'
  
  // Closing
  text += applyBoldItalic('Please note that this message was generated automatically.') + '\n\n'
  text += 'Please send your payment screenshot after transfer. Thank you.'
  
  return text
}

/**
 * Format currency without symbol
 */
function formatCurrencyNoSymbol(amount: number): string {
  return new Intl.NumberFormat('en-NG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount)
}

/**
 * URL encode text for WhatsApp
 */
export function encodeWhatsAppText(text: string): string {
  return encodeURIComponent(text)
}
