-- Basic arithmetic
print("=== Arithmetic Tests ===")
print(2 + 3)
print(10 - 4)
print(5 * 6)
print(20 / 4)
print(17 % 5)
print(2 ^ 8)

-- Variables
print("\n=== Variable Tests ===")
local x = 10
local y = 20
print(x + y)

a = 5
b = 7
print(a * b)

-- Strings
print("\n=== String Tests ===")
local name = "Lua"
print("Hello, " .. name .. "!")
print(#name)

-- Tables
print("\n=== Table Tests ===")
local t = {10, 20, 30, 40}
print(t[1])
print(t[2])
print(#t)

local person = {name = "John", age = 30}
print(person.name)
print(person.age)

-- Functions
print("\n=== Function Tests ===")
function add(a, b)
    return a + b
end
print(add(5, 3))

function factorial(n)
    if n <= 1 then
        return 1
    else
        return n * factorial(n - 1)
    end
end
print(factorial(5))

-- Conditionals
print("\n=== Conditional Tests ===")
local num = 15
if num > 10 then
    print("Greater than 10")
elseif num > 5 then
    print("Greater than 5")
else
    print("5 or less")
end

-- Loops
print("\n=== Loop Tests ===")
print("For loop:")
for i = 1, 5 do
    print(i)
end

print("While loop:")
local counter = 1
while counter <= 3 do
    print(counter)
    counter = counter + 1
end

print("Repeat loop:")
local count = 1
repeat
    print(count)
    count = count + 1
until count > 3

-- Boolean operators
print("\n=== Boolean Tests ===")
print(true and false)
print(true or false)
print(not true)
print(10 > 5)
print(5 == 5)
print(5 ~= 3)

print("\n=== All tests complete! ===")
