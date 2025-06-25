import json
import re
import os
import logging
import boto3
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from botocore.exceptions import ClientError, BotoCoreError
import time
from botocore.config import Config
import tempfile
import threading
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class GenerationRequest:
    """Data class for code generation requests."""
    parsed_data: Dict[str, Any]
    target_language: str
    framework: str
    coding_standards: str
    architecture_pattern: str
    include_tests: bool
    include_docs: bool
    custom_instructions: Optional[str] = None

@dataclass
class GenerationResponse:
    """Data class for code generation responses."""
    success: bool
    generated_code: Dict[str, Any]
    error_message: Optional[str] = None
    usage_stats: Optional[Dict[str, Any]] = None

class ClaudeClient:
    """Client for interacting with Claude Sonnet 4.0 API with autonomous completion."""
   
    def __init__(self, credentials_file: str = None, model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
                 aws_profile: str = "default", aws_region: str = "us-east-1"):
        """Initialize Claude client with AWS credentials."""
        self.aws_profile = aws_profile
        self.aws_region = aws_region
        self.model_id = model
        self.bedrock_client = self._initialize_bedrock_client()
        self.max_tokens = 8000
        self.temperature = 0.1
       
    def _initialize_bedrock_client(self):
        """Initialize the AWS Bedrock client."""
        try:
            config = Config(
                read_timeout=1200,  # 20 minutes for complete responses
                connect_timeout=60,
                max_pool_connections=50,
                retries={
                    'max_attempts': 5,
                    'mode': 'adaptive',
                    'total_max_attempts': 5
                },
                region_name=self.aws_region
            )

            session = boto3.Session(profile_name=self.aws_profile)
            bedrock_client = session.client(
                service_name='bedrock-runtime',
                region_name=self.aws_region,
                config=config
            )
           
            logger.info(f"Successfully initialized Bedrock client with profile: {self.aws_profile}")
            logger.info(f"Configured with read_timeout=1200s for complete responses")
            return bedrock_client
           
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {str(e)}")
            raise ValueError(f"Failed to initialize AWS Bedrock client: {str(e)}")
   
    def generate_code(self, request: GenerationRequest) -> GenerationResponse:
        """Generate code with multiple continuation attempts if needed."""
        max_attempts = 3
        max_continuations = 10  # Allow up to 5 continuations
       
        for attempt in range(max_attempts):
            try:
                logger.info(f"🚀 Generation attempt {attempt + 1}/{max_attempts}")
               
                # Step 1: Get initial response
                initial_response, raw_file_path = self._get_initial_response(request, attempt)
                current_response = initial_response
                continuation_count = 0
               
                # Step 2: Keep continuing until complete
                while self._needs_continuation(current_response) and continuation_count < max_continuations:
                    continuation_count += 1
                    logger.info(f"🔄 Continuation {continuation_count}/{max_continuations}...")
                   
                    continuation_response = self._get_continuation_response(current_response, request, attempt)
                    current_response = self._merge_responses(current_response, continuation_response)
                   
                    # Save intermediate result
                    intermediate_file = raw_file_path.replace('.txt', f'_CONT{continuation_count}.txt')
                    with open(intermediate_file, 'w', encoding='utf-8') as f:
                        f.write(current_response)
               
                # Step 3: Final check
                if continuation_count >= max_continuations:
                    logger.warning(f"⚠️ Reached max continuations ({max_continuations}) - using current response")
                else:
                    logger.info(f"✅ Response completed after {continuation_count} continuations")
               
                # Save final response
                final_file_path = raw_file_path.replace('.txt', '_FINAL.txt')
                with open(final_file_path, 'w', encoding='utf-8') as f:
                    f.write(current_response)
               
                # Step 4: Parse and return
                generated_code = self._parse_response(current_response)
               
                return GenerationResponse(
                    success=True,
                    generated_code=generated_code,
                    usage_stats={
                        'response_length': len(current_response),
                        'continuations_used': continuation_count,
                        'attempt': attempt + 1,
                        'raw_response_file': final_file_path
                    }
                )
               
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_attempts - 1:
                    time.sleep(30)
                    continue
                else:
                    return GenerationResponse(
                        success=False,
                        generated_code={},
                        error_message=str(e)
                    )
       
        return GenerationResponse(
            success=False,
            generated_code={},
            error_message="All attempts failed"
        )
   
    def _needs_continuation(self, response: str) -> bool:
        """Enhanced continuation detection - stricter completion checking."""
        if len(response) < 2000:  # Too short
            return True
       
        # Check for obvious incompleteness
        completion_checks = [
            # Response ends abruptly mid-line
            lambda r: not r.rstrip().endswith(('```', '}', '"', ';', '>', ']', 'EndGlobal')),
           
            # Unbalanced code blocks
            lambda r: r.count('```') % 2 != 0,
           
            # Significant brace imbalance (more than 10% difference)
            lambda r: abs(r.count('{') - r.count('}')) > max(10, (r.count('{') + r.count('}')) * 0.1),
           
            # Has project structure but missing key files
            lambda r: '.API' in r and '.Desktop' in r and r.count('**FILE:') < 20,
           
            # Cut off mid-sentence or mid-word
            lambda r: r.rstrip().endswith(('pattern: "{controller=', 'var ', 'public ', 'private ')),
           
            # Missing essential completions for web projects
            lambda r: 'Program.cs' in r and 'app.Run()' not in r,
            lambda r: 'Controllers' in r and 'MapControllers' not in r,
           
            # Still has incomplete FILE blocks
            lambda r: r.count('**FILE:') > r.count('```')/2,  # Each file should have at least 2 code blocks
        ]
       
        failed_checks = []
        for i, check in enumerate(completion_checks):
            try:
                if check(response):
                    failed_checks.append(f"check_{i+1}")
            except Exception:
                continue
       
        needs_more = len(failed_checks) > 0
       
        if needs_more:
            logger.warning(f"🔍 Incompleteness detected: {len(failed_checks)} issues")
            logger.warning(f"🔍 Failed checks: {', '.join(failed_checks)}")
            logger.warning(f"🔍 Response ends: ...{response[-100:].strip()}")
        else:
            logger.info("✅ Response appears complete")
       
        return needs_more
   
    def _get_continuation_response(self, initial_response: str, request: GenerationRequest, attempt: int) -> str:
        """Request continuation of incomplete response."""
       
        # Build continuation prompt with original requirements
        continuation_prompt = self._build_continuation_prompt(initial_response, request)
       
        # Configure continuation request
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8000,  # Same as initial
            "temperature": 0.05,  # Lower for consistency
            "messages": [{"role": "user", "content": continuation_prompt}],
            "stop_sequences": []
        }
       
        logger.info("📡 Sending continuation request...")
       
        try:
            response = self.bedrock_client.invoke_model_with_response_stream(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType='application/json',
                accept='application/json'
            )
           
            # Create continuation file
            continuation_file = self._create_continuation_file()
           
            # Process continuation response
            continuation_response = self._process_streaming_simple(response, continuation_file)
           
            logger.info(f"📄 Continuation received: {len(continuation_response)} chars")
            return continuation_response
           
        except Exception as e:
            logger.error(f"Continuation request failed: {str(e)}")
            return ""

    def _build_continuation_prompt(self, initial_response: str, request: GenerationRequest) -> str:
        """Build prompt to continue incomplete response with missing file type awareness."""
   
        # Extract original requirements
        parsed_data = request.parsed_data
        story_info = parsed_data.get('story_info', {})
        acceptance_criteria = parsed_data.get('acceptance_criteria', [])
        business_value = parsed_data.get('business_value', {})
       
        # Analyze what file types are missing from initial response
        missing_file_types = self._analyze_missing_file_types(initial_response, request)
       
        # Get context from end of response
        context = initial_response[-1000:] if len(initial_response) > 1000 else initial_response
       
        continuation_prompt = f"""CONTINUATION REQUEST: The previous C# .NET 8 code generation was incomplete.

    ## ORIGINAL REQUIREMENTS:
    **Project**: {story_info.get('summary', 'Generated Project')}
    **User Story**: {story_info.get('user_story', 'Complete the application')}

    **Acceptance Criteria**:"""

        # Add acceptance criteria
        for i, criterion in enumerate(acceptance_criteria[:5], 1):
            continuation_prompt += f"\n{i}. {criterion}"
       
        continuation_prompt += f"""

    **Business Purpose**: {business_value.get('description', 'Complete business application')}

    ## INCOMPLETE RESPONSE ANALYSIS:
    The response was cut off. Here's where it ended:

    {context}

    ## MISSING FILE TYPES DETECTED:"""

        # Add missing file types
        if missing_file_types:
            for file_type, description in missing_file_types.items():
                continuation_prompt += f"\n- **{file_type.upper()}**: {description}"
        else:
            continuation_prompt += "\n- Continue completing any unfinished files and add any missing components"

        continuation_prompt += """

    ## CONTINUATION INSTRUCTIONS:
    Please complete ALL missing parts to satisfy the original requirements:

    1. **Continue from where the response ended** - don't repeat existing code
    2. **Complete any unfinished files** that were cut off
    3. **Add any MISSING FILE TYPES** identified above
    4. **Generate ALL missing files** needed to meet acceptance criteria
    5. **Ensure the complete solution compiles and runs**
    6. **Use the same **FILE:** format** for consistency
    7. **Focus on C# .NET 8 code** with supporting files as needed

    IMPORTANT:
    - This is a CONTINUATION to complete missing functionality
    - Satisfy ALL acceptance criteria with appropriate file types
    - Include tests, styling, documentation as identified in requirements
    - Make the final solution fully functional and complete

    Continue with the missing components:"""

        return continuation_prompt

    def _analyze_missing_file_types(self, response: str, request: GenerationRequest) -> Dict[str, str]:
        """Analyze what file types are missing from the response."""
       
        missing_types = {}
       
        try:
            # Get required file types from original analysis
            parsed_data = request.parsed_data
            acceptance_criteria = parsed_data.get('acceptance_criteria', [])
            business_value = parsed_data.get('business_value', {})
            class_diagram = parsed_data.get('class_diagram', {})
            sequence_diagram = parsed_data.get('sequence_diagram', {})
           
            required_file_types = self._analyze_required_file_types(
                acceptance_criteria, business_value, class_diagram, sequence_diagram
            )
           
            # Check what's missing from response
            response_lower = response.lower()
           
            # Check for missing test files
            if 'test_files' in required_file_types:
                if not any(test_indicator in response_lower for test_indicator in [
                    'test.cs', 'tests.cs', 'xunit', '[fact]', '[test]', 'assert.'
                ]):
                    missing_types['test_files'] = required_file_types['test_files']
           
            # Check for missing CSS files
            if 'styling_files' in required_file_types:
                if not any(style_indicator in response for style_indicator in [
                    '.css', 'stylesheet', 'style.css', 'wwwroot', 'styling'
                ]):
                    missing_types['styling_files'] = required_file_types['styling_files']
           
            # Check for missing JavaScript files
            if 'client_scripts' in required_file_types:
                if not any(js_indicator in response for js_indicator in [
                    '.js', 'javascript', 'script.js', 'site.js', 'client-side'
                ]):
                    missing_types['client_scripts'] = required_file_types['client_scripts']
           
            # Check for missing API documentation
            if 'api_documentation' in required_file_types:
                if not any(doc_indicator in response_lower for doc_indicator in [
                    'api_documentation', 'swagger', 'openapi', 'api guide', 'endpoint'
                ]):
                    missing_types['api_documentation'] = required_file_types['api_documentation']
           
            # Check for missing comprehensive documentation
            if 'documentation_files' in required_file_types:
                doc_files_found = response.count('README.md') + response.count('User_Guide') + response.count('Developer_Guide')
                if doc_files_found < 2:  # Should have at least README + one other doc
                    missing_types['documentation_files'] = required_file_types['documentation_files']
           
            # Check for missing database files
            if 'database_files' in required_file_types:
                if not any(db_indicator in response_lower for db_indicator in [
                    '.sql', 'migration', 'seed', 'database', 'dbcontext'
                ]):
                    missing_types['database_files'] = required_file_types['database_files']
           
            logger.info(f"🔍 Missing file types detected: {list(missing_types.keys())}")
            return missing_types
           
        except Exception as e:
            logger.warning(f"Missing file type analysis failed: {str(e)}")
            return {}

    def _merge_responses(self, initial: str, continuation: str) -> str:
        """Merge initial and continuation responses."""
        if not continuation.strip():
            logger.warning("⚠️ Empty continuation received")
            return initial
       
        # Simple merge with separator
        merged = initial.rstrip() + "\n\n" + continuation.strip()
       
        logger.info(f"🔗 Merged responses: {len(initial)} + {len(continuation)} = {len(merged)} chars")
       
        return merged

    def _create_continuation_file(self) -> str:
        """Create file for continuation response."""
        output_dir = Path("generated_output")
        output_dir.mkdir(exist_ok=True)
       
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        continuation_file_path = output_dir / f"continuation_response_{timestamp}.txt"
       
        logger.info(f"📁 Created continuation file: {continuation_file_path}")
        return str(continuation_file_path)

    # Remove/Replace these old methods to avoid conflicts:
    def _generate_with_completion_detection(self, prompt: str, attempt: int):
        """DEPRECATED - Use _get_initial_response instead"""
        logger.warning("🚨 Using deprecated method - please update caller")
        return self._get_initial_response_legacy(prompt, attempt)

    def _process_autonomous_streaming(self, response, raw_file_path: str):
        """DEPRECATED - Use _process_streaming_simple instead"""
        logger.warning("🚨 Using deprecated method - please update caller")
        return self._process_streaming_simple(response, raw_file_path)

    # Keep these methods as-is (no changes needed):
    # - _build_complete_prompt()
    # - _create_autonomous_raw_file()  
    # - _parse_response()
    # - All the formatting methods (_format_*)

    # Optional: Add a simple test method for the new approach
    def test_continuation_approach(self):
        """Test the new continuation approach with minimal data."""
        test_data = {
            "story_info": {
                "summary": "Test Continuation",
                "user_story": "As a developer, I want to test continuation, so that incomplete responses are completed"
            },
            "acceptance_criteria": [
                "Generate a complete console application",
                "Include proper project structure",
                "Code should compile successfully"
            ],
            "business_value": {
                "description": "Test the continuation functionality"
            },
            "class_diagram": {"classes": ["TestClass"]},
            "sequence_diagram": {"participants": ["User", "System"]}
        }
       
        request = GenerationRequest(
            parsed_data=test_data,
            target_language="csharp",
            framework="net8.0",
            coding_standards="Microsoft",
            architecture_pattern="Simple",
            include_tests=False,
            include_docs=False
        )
       
        logger.info("🧪 Testing continuation approach...")
        response = self.generate_code(request)

    def _get_initial_response(self, request: GenerationRequest, attempt: int) -> tuple[str, str]:
        """Get the initial response from AI."""
        # Build the prompt
        prompt = self._build_complete_prompt(request)
       
        # Configure request
        max_tokens = 8000  # Keep your existing limit
        temperature = 0.1
       
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "stop_sequences": []
        }
       
        logger.info(f"📡 Sending initial request (tokens: {max_tokens})")
       
        # Create raw response file
        raw_response_path = self._create_autonomous_raw_file()
       
        try:
            response = self.bedrock_client.invoke_model_with_response_stream(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType='application/json',
                accept='application/json'
            )
           
            # Process streaming response
            complete_response = self._process_streaming_simple(response, raw_response_path)
           
            return complete_response, raw_response_path
           
        except Exception as e:
            logger.error(f"Initial response failed: {str(e)}")
            raise

    def _process_streaming_simple(self, response, raw_file_path: str) -> str:
        """Simple streaming processor without auto-healing."""
        full_response = ""
        chunk_count = 0
       
        try:
            with open(raw_file_path, 'w', encoding='utf-8') as raw_file:
                stream = response.get('body')
               
                if stream:
                    for event in stream:
                        chunk = event.get('chunk')
                        if chunk:
                            chunk_data = json.loads(chunk.get('bytes').decode())
                           
                            if chunk_data.get('type') == 'content_block_delta':
                                delta = chunk_data.get('delta', {})
                                if 'text' in delta:
                                    text_chunk = delta['text']
                                    full_response += text_chunk
                                    chunk_count += 1
                                   
                                    # Write to raw file immediately
                                    raw_file.write(text_chunk)
                                    raw_file.flush()
                                   
                                    # Log progress every 2000 characters
                                    if len(full_response) % 2000 == 0:
                                        logger.info(f"📊 Progress: {len(full_response)} chars")
                           
                            elif chunk_data.get('type') == 'message_stop':
                                logger.info("✅ Claude signaled completion")
                                break
           
            logger.info(f"📄 Initial response captured: {len(full_response)} chars, {chunk_count} chunks")
            return full_response
           
        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            return full_response

    def _build_complete_prompt(self, request: GenerationRequest) -> str:
        """Build focused prompt that requests ALL necessary file types based on requirements analysis."""

        # Extract key information from parsed data
        parsed_data = request.parsed_data
        story_info = parsed_data.get('story_info', {})
        acceptance_criteria = parsed_data.get('acceptance_criteria', [])[:5]
        business_value = parsed_data.get('business_value', {})
        class_diagram = parsed_data.get('class_diagram', {})
        sequence_diagram = parsed_data.get('sequence_diagram', {})
       
        project_name = story_info.get('summary', 'GeneratedProject').replace(' ', '')
        if not project_name or len(project_name) < 3:
            project_name = 'GeneratedProject'
       
        # ANALYZE REQUIREMENTS TO DETERMINE WHAT FILE TYPES ARE NEEDED
        required_file_types = self._analyze_required_file_types(
            acceptance_criteria, business_value, class_diagram, sequence_diagram
        )
       
        # Build focused, comprehensive prompt
        prompt = f"""Create a complete C# .NET 8 project for: {project_name}

    ## USER REQUIREMENTS:
    **Goal**: {story_info.get('user_story', 'Create a functional application')}

    **Key Features Required**:"""
       
        # Add acceptance criteria
        for i, criterion in enumerate(acceptance_criteria, 1):
            prompt += f"\n{i}. {criterion}"
       
        if not acceptance_criteria:
            prompt += "\n1. Create a functional application\n2. Include proper error handling\n3. Follow Microsoft coding standards"
       
        prompt += f"""

    **Business Purpose**: {business_value.get('description', 'Business application')}

    ## TECHNICAL REQUIREMENTS:
    **Classes to Implement**: {', '.join(class_diagram.get('classes', ['MainClass', 'Service'])[:6])}
    **User Interactions**: {', '.join(sequence_diagram.get('participants', ['User', 'System']))}

    ## COMPREHENSIVE FILE GENERATION REQUIREMENTS:
    Based on analysis, generate ALL of the following file types:

    ### 1. CORE APPLICATION FILES:
    - Complete solution (.sln) and project files (.csproj)
    - All C# classes, interfaces, and services as identified from requirements
    - Program.cs with proper startup configuration
    - Configuration files (appsettings.json, app.config as needed)

    ### 2. REQUIRED FILE TYPES (Based on Requirements Analysis):"""

        # Add file type requirements based on analysis
        for file_type, requirement in required_file_types.items():
            prompt += f"\n- **{file_type.upper()}**: {requirement}"

        prompt += f"""

    ## OUTPUT INSTRUCTIONS:
    Provide complete working files in this exact format:

    **FILE: {project_name}.sln**
    [Complete solution file content]


    **FILE: src/{project_name}.Desktop/{project_name}.Desktop.csproj**
    ```xml
    [Complete project file with dependencies]
    FILE: src/{project_name}.Desktop/Program.cs

    [Complete Program.cs with Main method]
    Continue this pattern for ALL required files including tests, styling, documentation, and any other files identified from the requirements analysis.

    CRITICAL: Generate ALL necessary files for a complete, working Visual Studio Web (Strictly No Windows Application) solution that satisfies every acceptance criteria. Include proper dependencies, error handling, and follow Microsoft coding standards. Make sure the application compiles and runs immediately with all requested functionality."""

        return prompt

    def _analyze_required_file_types(self, acceptance_criteria: List[str], business_value: Dict[str, Any],
                               class_diagram: Dict[str, Any], sequence_diagram: Dict[str, Any]) -> Dict[str, str]:
        """Analyze requirements to determine what file types are needed - NO HARDCODING"""
       
        required_files = {}
       
        try:
            # Combine all requirement text for analysis
            all_requirements = ' '.join(acceptance_criteria).lower()
            business_desc = business_value.get('description', '').lower()
            class_names = ' '.join(class_diagram.get('classes', [])).lower()
            participants = ' '.join(sequence_diagram.get('participants', [])).lower()
           
            combined_requirements = f"{all_requirements} {business_desc} {class_names} {participants}"
           
            # Analyze for test requirements
            test_indicators = ['test', 'testing', 'quality', 'validation', 'verify', 'ensure', 'check']
            if any(indicator in combined_requirements for indicator in test_indicators):
                required_files['test_files'] = "Generate comprehensive unit tests using xUnit framework for all business logic classes and integration tests for API endpoints"
           
            # Analyze for UI/styling requirements
            ui_indicators = ['grid', 'display', 'user interface', 'ui', 'form', 'styling', 'appearance', 'visual', 'design']
            if any(indicator in combined_requirements for indicator in ui_indicators):
                required_files['styling_files'] = "Generate CSS files for styling and visual appearance of user interface components"
           
            # Analyze for interactive functionality
            interactive_indicators = ['interactive', 'click', 'button', 'input', 'filter', 'sort', 'search', 'dynamic']
            if any(indicator in combined_requirements for indicator in interactive_indicators):
                required_files['client_scripts'] = "Generate JavaScript files for client-side interactivity and dynamic functionality"
           
            # Analyze for API/web service requirements
            api_indicators = ['api', 'service', 'endpoint', 'rest', 'web service', 'controller', 'http']
            if any(indicator in combined_requirements for indicator in api_indicators):
                required_files['api_documentation'] = "Generate comprehensive API documentation including endpoint descriptions, request/response examples, and usage guides"
           
            # Analyze for data/database requirements
            data_indicators = ['database', 'data', 'sql', 'entity', 'model', 'repository', 'connection']
            if any(indicator in combined_requirements for indicator in data_indicators):
                required_files['database_files'] = "Generate database setup scripts, entity models, and data access layer components"
           
            # Analyze for configuration requirements
            config_indicators = ['configuration', 'settings', 'environment', 'deployment', 'setup']
            if any(indicator in combined_requirements for indicator in config_indicators):
                required_files['configuration_files'] = "Generate comprehensive configuration files for different environments and deployment scenarios"
           
            # Analyze for documentation requirements
            doc_indicators = ['documentation', 'readme', 'guide', 'manual', 'instructions', 'help']
            if any(indicator in combined_requirements for indicator in doc_indicators):
                required_files['documentation_files'] = "Generate comprehensive documentation including user guides, developer documentation, and setup instructions"
           
            # Always include basic requirements if nothing specific found
            if not required_files:
                required_files['basic_structure'] = "Generate complete project structure with all necessary files for a functional application"
           
            # Log what was detected for debugging
            logger.info(f"📋 File type analysis detected: {list(required_files.keys())}")
           
            return required_files
           
        except Exception as e:
            logger.warning(f"File type analysis failed: {str(e)}")
            return {'basic_structure': 'Generate complete project structure with all necessary files'}

    def _generate_with_completion_detection(self, prompt: str, attempt: int) -> tuple[str, str]:
        """Generate with streaming - NO auto-healing to prevent corruption"""
        max_tokens = min(8000, 6000 + (attempt * 1000))  # START HIGHER
        temperature = max(0.05, 0.15 - (attempt * 0.02))
       
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "stop_sequences": []  # No stop sequences
        }
           
        logger.info(f"🌊 Starting generation (tokens: {max_tokens}, temp: {temperature})")
       
        # Create raw response file
        raw_response_path = self._create_autonomous_raw_file()
           
        try:
            response = self.bedrock_client.invoke_model_with_response_stream(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType='application/json',
                accept='application/json'
            )
           
            # Process streaming WITHOUT auto-healing
            complete_response = self._process_autonomous_streaming(response, raw_response_path)
           
            return complete_response, raw_response_path
           
        except Exception as e:
            logger.error(f"Streaming generation failed: {str(e)}")
            raise
           
        except Exception as e:
            logger.error(f"Streaming generation failed: {str(e)}")
            raise

    def _create_autonomous_raw_file(self) -> str:
        """Create autonomous raw response file with auto-cleanup."""
        # Ensure output directory exists
        output_dir = Path("generated_output")
        output_dir.mkdir(exist_ok=True)
       
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_file_path = output_dir / f"raw_response_{timestamp}.txt"
       
        logger.info(f"📁 Created autonomous raw response file: {raw_file_path}")
        return str(raw_file_path)
   
    def _process_autonomous_streaming(self, response, raw_file_path: str) -> str:
        """Process streaming WITH truncation detection and auto-completion"""
        full_response = ""
        last_chunk_time = time.time()
        chunk_count = 0
       
        try:
            with open(raw_file_path, 'w', encoding='utf-8') as raw_file:
                stream = response.get('body')
               
                if stream:
                    for event in stream:
                        chunk = event.get('chunk')
                        if chunk:
                            chunk_data = json.loads(chunk.get('bytes').decode())
                           
                            if chunk_data.get('type') == 'content_block_delta':
                                delta = chunk_data.get('delta', {})
                                if 'text' in delta:
                                    text_chunk = delta['text']
                                    full_response += text_chunk
                                    chunk_count += 1
                                   
                                    # Write to raw file immediately
                                    raw_file.write(text_chunk)
                                    raw_file.flush()
                                   
                                    # Update progress
                                    last_chunk_time = time.time()
                                   
                                    # Log progress every 2000 characters
                                    if len(full_response) % 2000 == 0:
                                        logger.info(f"📊 Progress: {len(full_response)} chars, {chunk_count} chunks")
                           
                            elif chunk_data.get('type') == 'message_stop':
                                logger.info("✅ Claude signaled completion")
                                break
                       
                        # FIXED: Increased timeout to 10 minutes
                        if time.time() - last_chunk_time > 600:  # 10 minutes
                            logger.warning("⏰ Extended timeout - Claude may be done")
                            break
           
            logger.info(f"📄 Raw response captured: {len(full_response)} chars, {chunk_count} chunks")
           
            # NEW: Auto-detect and complete truncated responses
            logger.info("🔍 Checking for truncation...")
            complete_response = self._detect_and_complete_truncated_response(full_response)
           
            if len(complete_response) > len(full_response):
                logger.info(f"✅ Response completed: {len(complete_response)} chars (added {len(complete_response) - len(full_response)})")
               
                # Save completed version
                completed_file_path = raw_file_path.replace('.txt', '_COMPLETED.txt')
                with open(completed_file_path, 'w', encoding='utf-8') as f:
                    f.write(complete_response)
               
                full_response = complete_response
           
            # Save as latest for autonomous pickup
            latest_path = Path("generated_output") / "raw_response_latest.txt"
            with open(latest_path, 'w', encoding='utf-8') as f:
                f.write(full_response)
            logger.info(f"💾 Saved response as latest: {latest_path}")
           
            return full_response
           
        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            return full_response
   
    def _auto_heal_response_autonomous(self, raw_response: str, raw_file_path: str) -> str:
        """AUTONOMOUS: Auto-heal without hardcoding any domain assumptions"""
        logger.info("🔧 Autonomous auto-healing (no assumptions)...")
       
        try:
            # Diagnose issues
            issues = self._diagnose_response_issues(raw_response)
           
            if not issues:
                logger.info("✅ Response is healthy")
                return raw_response
           
            logger.info(f"🩺 Issues detected: {', '.join(issues)}")
           
            # Apply generic healing (no domain assumptions)
            healed_response = self._apply_generic_healing(raw_response, issues)
           
            # Save healed version
            healed_file = raw_file_path.replace('.txt', '_HEALED.txt')
            with open(healed_file, 'w', encoding='utf-8') as f:
                f.write(healed_response)
       
            logger.info(f"💊 Healed response saved: {healed_file}")
            return healed_response
       
        except Exception as e:
            logger.warning(f"🩹 Auto-healing failed: {str(e)}")
            return raw_response

    def _apply_generic_healing(self, response: str, issues: list) -> str:
        """Apply generic healing fixes without domain assumptions"""
        healed = response
       
        try:
            if "unclosed_json_block" in issues:
                healed = self._fix_unclosed_json_block_generic(healed)
           
            if "unterminated_string" in issues:
                healed = self._fix_unterminated_strings_generic(healed)
           
            if "unbalanced_braces" in issues:
                healed = self._fix_unbalanced_braces_generic(healed)
           
            if "abrupt_ending" in issues:
                healed = self._fix_abrupt_ending_generic(healed)
           
            return healed
           
        except Exception as e:
            logger.warning(f"Generic healing failed: {str(e)}")
            return response

    def _fix_unclosed_json_block_generic(self, response: str) -> str:
        """Fix unclosed JSON blocks generically"""
        if '```json' in response and response.count('```') % 2 != 0:
            last_json = response.rfind('```json')
            if last_json != -1:
                after_json = response[last_json + 7:]
                # Find last complete structure
                for i in range(len(after_json) - 1, -1, -1):
                    if after_json[i] in ['}', ']', '"']:
                        closing_point = last_json + 7 + i + 1
                        return response[:closing_point] + '\n```'
        return response

    def _fix_unterminated_strings_generic(self, response: str) -> str:
        """Fix unterminated strings without domain assumptions"""
        json_start = response.find('```json')
        if json_start == -1:
            return response
       
        json_start += 7
        json_end = response.find('```', json_start)
       
        if json_end == -1:
            json_content = response[json_start:]
            rest_of_response = ""
        else:
            json_content = response[json_start:json_end]
            rest_of_response = response[json_end:]
       
        # Generic fixes for unterminated strings
        lines = json_content.split('\n')
        fixed_lines = []
       
        for line in lines:
            stripped = line.strip()
           
            # If line starts with quote but doesn't end properly
            if (stripped.startswith('"') and
                not stripped.endswith('"') and
                not stripped.endswith('",') and
                ':' in stripped):
               
                # Complete the string generically
                key_part, value_part = stripped.split(':', 1)
                value_part = value_part.strip()
                if value_part.startswith('"') and not value_part.endswith('"'):
                    line = f'{key_part}: "{value_part[1:]} [auto-completed]"'
           
            fixed_lines.append(line)
       
        return response[:response.find('```json') + 7] + '\n'.join(fixed_lines) + rest_of_response

    def _fix_unbalanced_braces_generic(self, response: str) -> str:
        """Fix unbalanced braces generically"""
        json_start = response.find('```json')
        if json_start == -1:
            return response
       
        json_start += 7
        json_end = response.find('```', json_start)
       
        if json_end == -1:
            json_content = response[json_start:]
            suffix = ""
        else:
            json_content = response[json_start:json_end]
            suffix = response[json_end:]
       
        # Count and balance braces generically
        open_braces = json_content.count('{')
        close_braces = json_content.count('}')
        open_brackets = json_content.count('[')
        close_brackets = json_content.count(']')
       
        # Add missing closing structures
        if open_braces > close_braces:
            json_content += '}' * (open_braces - close_braces)
       
        if open_brackets > close_brackets:
            json_content += ']' * (open_brackets - close_brackets)
       
        return response[:response.find('```json') + 7] + json_content + suffix

    def _fix_abrupt_ending_generic(self, response: str) -> str:
        """Fix abrupt endings generically"""
        if not response.strip().endswith(('}', '```', '"')):
            # Find last meaningful content
            last_meaningful = max(
                response.rfind('}'),
                response.rfind('"'),
                response.rfind(']'),
                response.rfind(',')
            )
           
            if last_meaningful > len(response) - 200:
                # Truncate at last meaningful point
                response = response[:last_meaningful + 1]
               
                # If in JSON block, close it properly
                if '```json' in response and not response.endswith('```'):
                    after_json = response[response.find('```json') + 7:]
                    open_braces = after_json.count('{') - after_json.count('}')
                   
                    if open_braces > 0:
                        response += '}' * open_braces
                    response += '\n```'
       
        return response

    def _detect_early_completion(self, response: str) -> bool:
        """Detect if response might be complete before end signal."""
        if len(response) < 1000:
            return False
       
        # Look for completion indicators in the last 500 characters
        tail = response[-500:]
       
        # Fixed regex patterns
        completion_signs = [
            r'\}\s*\$',  # Ends with closing brace
            r'```\s*\$',  # Ends with code block
            r'"configuration":\s*\{[^}]*\}\s*\}',  # Configuration section complete
            r'"dependencies":\s*$$[^$$]*$$\s*,?',  # Dependencies section
            r'"files":\s*\{[^}]*\}\s*\}',  # Files section complete
        ]
       
        try:
            return any(re.search(pattern, tail, re.MULTILINE | re.DOTALL) for pattern in completion_signs)
        except re.error as e:
            logger.warning(f"Regex error in completion detection: {str(e)}")
            return False
   
    def _is_response_complete(self, response: str) -> bool:
        """Simplified completion check focused on actual content"""
        if len(response) < 800:  # Too short
            return False
       
        try:
            # Count meaningful indicators
            file_blocks = response.count('**FILE:') + response.count('```csharp') + response.count('```xml')
            has_project_files = '.csproj' in response or '.sln' in response
            has_code = any(keyword in response for keyword in ['namespace', 'class', 'using System'])
            has_ending = any(ending in response[-300:] for ending in ['```', 'EndProject', 'EndGlobal', '}'])
           
            # Score-based completion
            completion_score = 0
            if file_blocks >= 3: completion_score += 2  # At least 3 files
            if has_project_files: completion_score += 1  # Has project structure
            if has_code: completion_score += 1          # Has actual code
            if has_ending: completion_score += 1        # Has proper ending
            if len(response) > 3000: completion_score += 1  # Substantial content
           
            is_complete = completion_score >= 4  # Need at least 4/6 points
           
            logger.info(f"Completion check: {completion_score}/6 - "
                    f"Files({file_blocks}), "
                    f"Project({has_project_files}), "
                    f"Code({has_code}), "
                    f"Ending({has_ending}) = {'✅' if is_complete else '❌'}")
           
            return is_complete
           
        except Exception as e:
            logger.warning(f"Completion check error: {str(e)}")
            return len(response) > 5000  # Fallback to length check

    def _build_prompt(self, request: GenerationRequest) -> str:
        """Build the prompt for Claude based on the request."""
       
        base_prompt = f"""
You are an expert software architect and {request.target_language} developer. Generate complete, production-ready code based on the following documentation.

## REQUIREMENTS:
1. Follow {request.coding_standards} coding standards and conventions
2. Implement {request.architecture_pattern} architecture pattern
3. Use {request.framework} framework and best practices
4. Include proper error handling and validation
5. Add comprehensive comments and documentation
6. Follow SOLID principles and design patterns
7. Make code maintainable, testable, and scalable
8. Include dependency injection where appropriate
9. Use async/await patterns where suitable
10. Include proper logging and monitoring hooks

## DOCUMENTATION PROVIDED:
"""

        # Add parsed documentation sections - Handle new format
        if request.parsed_data.get('metadata'):
            base_prompt += f"\n### PROJECT METADATA:\n{self._format_metadata(request.parsed_data['metadata'])}\n"
       
        # Handle both old and new user story formats
        if request.parsed_data.get('user_story'):
            base_prompt += f"\n### USER STORY:\n{self._format_user_story(request.parsed_data['user_story'])}\n"
        elif request.parsed_data.get('story_info'):
            base_prompt += f"\n### STORY INFO:\n{self._format_story_info(request.parsed_data['story_info'])}\n"
       
        # Handle both old and new acceptance criteria formats
        if request.parsed_data.get('acceptance_criteria'):
            base_prompt += f"\n### ACCEPTANCE CRITERIA:\n{self._format_acceptance_criteria_flexible(request.parsed_data['acceptance_criteria'])}\n"
       
        # Handle both old and new business requirements formats
        if request.parsed_data.get('business_requirements'):
            base_prompt += f"\n### BUSINESS REQUIREMENTS:\n{self._format_business_requirements(request.parsed_data['business_requirements'])}\n"
        elif request.parsed_data.get('business_value'):
            base_prompt += f"\n### BUSINESS VALUE:\n{self._format_business_value(request.parsed_data['business_value'])}\n"
       
        # Handle both old and new diagram formats
        if request.parsed_data.get('diagrams'):
            base_prompt += f"\n### TECHNICAL DESIGN:\n{self._format_diagrams(request.parsed_data['diagrams'])}\n"
        elif request.parsed_data.get('class_diagram') or request.parsed_data.get('sequence_diagram'):
            base_prompt += f"\n### TECHNICAL DESIGN:\n{self._format_new_diagrams(request.parsed_data)}\n"
       
        # Add output format instructions
        base_prompt += f"""

    ## OUTPUT FORMAT:
    Return a JSON structure with the following format:
    ```json
    {{
        "project_structure": {{
            "solution_name": "ProjectName",
            "projects": [
                {{
                    "name": "ProjectName.Core",
                    "type": "ClassLibrary",
                    "framework": "{request.framework}"
                }}
            ]
        }},
        "files": {{
            "file_path": {{
                "content": "file_content",
                "type": "csharp|json|xml|md"
            }}
        }},
        "dependencies": [
            {{
                "package": "Microsoft.Extensions.DependencyInjection",
                "version": "8.0.0"
            }}
        ],
        "configuration": {{
            "appsettings": {{}},
            "startup_configuration": ""
        }}
    }}
    SPECIFIC INSTRUCTIONS: """

        # Add specific language instructions
        if request.target_language.lower() == 'csharp':
            base_prompt += self._get_csharp_instructions(request)
       
        # Add testing instructions if requested
        if request.include_tests:
            base_prompt += """
    Generate comprehensive unit tests using xUnit framework Include integration tests where appropriate Use mocking frameworks (Moq) for dependencies Achieve high code coverage Include test data builders and fixtures"""

        # Add documentation instructions if requested
        if request.include_docs:
            base_prompt += """
    Generate XML documentation comments for all public members Create README.md with setup and usage instructions Include API documentation if applicable Add inline comments for complex business logic"""

        # Add custom instructions if provided
        if request.custom_instructions:
            base_prompt += f"\n### ADDITIONAL INSTRUCTIONS:\n{request.custom_instructions}\n"

        base_prompt += """
    Generate complete, working code that can be compiled and run immediately. Ensure all classes, interfaces, and dependencies are properly defined and implemented."""

        return base_prompt

    def _get_csharp_instructions(self, request: GenerationRequest) -> str:
        """Get C#-specific generation instructions."""
        return f"""
    C# SPECIFIC REQUIREMENTS:
    Use nullable reference types and proper null handling
    Implement IDisposable pattern where appropriate
    Use records for DTOs and value objects
    Implement proper exception handling with custom exceptions
    Use ConfigureAwait(false) for async operations in libraries
    Follow Microsoft naming conventions (PascalCase for public members)
    Use expression-bodied members where appropriate
    Implement generic constraints properly
    Use span and memory types for performance-critical code
    Include proper validation using FluentValidation or DataAnnotations
    Use minimal APIs for web applications when appropriate
    Implement health checks and monitoring endpoints
    Use structured logging with ILogger<T>
    Include OpenAPI/Swagger documentation for APIs
    Use Entity Framework Core with proper DbContext configuration
    Implement repository and unit of work patterns
    Use MediatR for CQRS implementation if applicable
    Include proper configuration management with IOptions<T>
    Use background services for long-running tasks
    Implement rate limiting and security best practices """

    def format_metadata(self, metadata: Dict[str, Any]) -> str:
        """Format metadata for the prompt."""
        formatted = []
        for key, value in metadata.items():
            formatted.append(f"- {key.replace('', ' ').title()}: {value}")
        return '\n'.join(formatted)

    def _format_user_story(self, user_story: Dict[str, Any]) -> str:
        """Format user story for the prompt."""
        formatted = []
        if user_story.get('persona'):
            formatted.append(f"As a {user_story['persona']}")
        if user_story.get('requirement'):
            formatted.append(f"I want {user_story['requirement']}")
        if user_story.get('benefit'):
            formatted.append(f"So that {user_story['benefit']}")
        return '\n'.join(formatted)
   
    def _format_story_info(self, story_info: Dict[str, Any]) -> str:
        """Format story info for the prompt (new format)."""
        formatted = []
        if story_info.get('story_key'):
            formatted.append(f"**Story Key:** {story_info['story_key']}")
        if story_info.get('summary'):
            formatted.append(f"**Summary:** {story_info['summary']}")
        if story_info.get('user_story'):
            formatted.append(f"**User Story:** {story_info['user_story']}")
        if story_info.get('status'):
            formatted.append(f"**Status:** {story_info['status']}")
        if story_info.get('assignee'):
            formatted.append(f"**Assignee:** {story_info['assignee']}")
        return '\n'.join(formatted)
   
    def _format_acceptance_criteria_flexible(self, criteria) -> str:
        """Format acceptance criteria handling both old and new formats."""
        formatted = []
       
        # Handle new format (list of strings)
        if isinstance(criteria, list) and criteria:
            if isinstance(criteria[0], str):
                # New format: list of strings
                for i, criterion in enumerate(criteria, 1):
                    formatted.append(f"{i}. {criterion}")
            else:
                # Old format: list of dicts
                for i, criterion in enumerate(criteria, 1):
                    if isinstance(criterion, dict):
                        formatted.append(f"{i}. {criterion.get('description', str(criterion))}")
                    else:
                        formatted.append(f"{i}. {str(criterion)}")
       
        return '\n'.join(formatted)
   
    def _format_business_requirements(self, requirements: Dict[str, Any]) -> str:
        """Format business requirements for the prompt (old format)."""
        formatted = []
       
        if requirements.get('business_values'):
            formatted.append("**Business Values:**")
            for key, value in requirements['business_values'].items():
                formatted.append(f"- {key.replace('_', ' ').title()}: {value}")
       
        if requirements.get('priority'):
            formatted.append(f"\n**Priority:** {requirements['priority']}")
       
        if requirements.get('story_points'):
            formatted.append(f"**Complexity:** {requirements['story_points']} points")
       
        if requirements.get('additional_notes'):
            formatted.append("\n**Additional Requirements:**")
            for note in requirements['additional_notes']:
                formatted.append(f"- {note}")
       
        return '\n'.join(formatted)
   
    def _format_business_value(self, business_value: Dict[str, Any]) -> str:
        """Format business value for the prompt (new format)."""
        formatted = []
       
        if business_value.get('description'):
            formatted.append(f"**Description:** {business_value['description']}")
       
        if business_value.get('benefits'):
            formatted.append("\n**Benefits:**")
            for benefit in business_value['benefits']:
                formatted.append(f"- {benefit}")
       
        if business_value.get('priority'):
            formatted.append(f"\n**Priority:** {business_value['priority']}")
       
        if business_value.get('story_points'):
            formatted.append(f"**Story Points:** {business_value['story_points']}")
       
        return '\n'.join(formatted)
   
    def _format_new_diagrams(self, parsed_data: Dict[str, Any]) -> str:
        """Format new diagram structure for the prompt."""
        formatted = []
       
        # Format class diagram
        class_diagram = parsed_data.get('class_diagram', {})
        if class_diagram:
            formatted.append("**Class Diagram:**")
            if class_diagram.get('classes'):
                formatted.append(f"- Classes: {', '.join(class_diagram['classes'])}")
            if class_diagram.get('raw_diagram'):
                formatted.append("- Diagram Structure:")
                formatted.append(f"```\n{class_diagram['raw_diagram'][:500]}...\n```")
            if class_diagram.get('relationships'):
                formatted.append(f"- Relationships: {len(class_diagram['relationships'])} defined")
       
        # Format sequence diagram
        sequence_diagram = parsed_data.get('sequence_diagram', {})
        if sequence_diagram:
            formatted.append("\n**Sequence Diagram:**")
            if sequence_diagram.get('participants'):
                formatted.append(f"- Participants: {', '.join(sequence_diagram['participants'])}")
            if sequence_diagram.get('interactions'):
                formatted.append(f"- Interactions: {len(sequence_diagram['interactions'])} defined")
            if sequence_diagram.get('raw_diagram'):
                formatted.append("- Flow Structure:")
                formatted.append(f"```\n{sequence_diagram['raw_diagram'][:500]}...\n```")
       
        return '\n'.join(formatted)
   
    def _format_diagrams(self, diagrams: Dict[str, Any]) -> str:
        """Format diagram information for the prompt with enhanced details (old format)."""
        formatted = []
       
        diagram_data = {k: v for k, v in diagrams.items() if not k.startswith('_')}
       
        if not diagram_data:
            return "No technical diagrams provided."
       
        for diagram_name, diagram_info in diagram_data.items():
            formatted.append(f"\n**{diagram_name.replace('_', ' ').title()}:**")
           
            if isinstance(diagram_info, dict) and 'type' in diagram_info:
                formatted.append(f"  Type: {diagram_info['type']}")
           
            if 'data' in diagram_info:
                diagram_data_obj = diagram_info['data']
               
                if hasattr(diagram_data_obj, 'classes'):
                    formatted.append(f"  Classes ({len(diagram_data_obj.classes)}):")
                    for class_name, class_entity in diagram_data_obj.classes.items():
                        formatted.append(f"    - {class_name}")
                        if hasattr(class_entity, 'properties') and class_entity.properties:
                            formatted.append(f"      Properties: {', '.join([p.get('name', 'Unknown') for p in class_entity.properties[:3]])}{'...' if len(class_entity.properties) > 3 else ''}")
                        if hasattr(class_entity, 'methods') and class_entity.methods:
                            formatted.append(f"      Methods: {', '.join([m.get('name', 'Unknown') for m in class_entity.methods[:3]])}{'...' if len(class_entity.methods) > 3 else ''}")
                   
                    if hasattr(diagram_data_obj, 'interfaces') and diagram_data_obj.interfaces:
                        formatted.append(f"  Interfaces ({len(diagram_data_obj.interfaces)}):")
                        for interface_name in list(diagram_data_obj.interfaces.keys())[:3]:
                            formatted.append(f"    - {interface_name}")
                   
                    if hasattr(diagram_data_obj, 'relationships') and diagram_data_obj.relationships:
                        formatted.append(f"  Relationships ({len(diagram_data_obj.relationships)}):")
                        for rel in diagram_data_obj.relationships[:3]:
                            formatted.append(f"    - {rel.from_entity} -> {rel.to_entity} ({rel.relationship_type.value})")
               
                elif hasattr(diagram_data_obj, 'actors'):
                    formatted.append(f"  Actors ({len(diagram_data_obj.actors)}):")
                    for actor in diagram_data_obj.actors[:5]:
                        formatted.append(f"    - {actor.name} ({actor.type})")
                   
                    if hasattr(diagram_data_obj, 'messages') and diagram_data_obj.messages:
                        formatted.append(f"  Key Interactions ({len(diagram_data_obj.messages)}):")
                        for msg in diagram_data_obj.messages[:5]:
                            formatted.append(f"    - {msg.from_actor} -> {msg.to_actor}: {msg.message}")
           
            if 'code_structure' in diagram_info and diagram_info['code_structure']:
                code_struct = diagram_info['code_structure']
                formatted.append("  Suggested Code Structure:")
               
                if 'classes' in code_struct:
                    formatted.append(f"    - C# Classes: {len(code_struct['classes'])}")
               
                if 'interfaces' in code_struct:
                    formatted.append(f"    - C# Interfaces: {len(code_struct['interfaces'])}")
               
                if 'controllers' in code_struct:
                    formatted.append(f"    - API Controllers: {len(code_struct['controllers'])}")
               
                if 'services' in code_struct:
                    formatted.append(f"    - Services: {len(code_struct['services'])}")
           
            if 'validation' in diagram_info and diagram_info['validation']:
                validation = diagram_info['validation']
                if validation.get('valid', True):
                    formatted.append("  ✅ Diagram validation passed")
                else:
                    formatted.append("  ⚠️ Diagram has validation issues")
                    if validation.get('errors'):
                        formatted.append(f"    Errors: {len(validation['errors'])}")
       
        if '_summary' in diagrams:
            summary = diagrams['_summary']
            formatted.append(f"\n**Diagram Summary:**")
            formatted.append(f"- Total diagrams: {summary.get('total_diagrams', 0)}")
            formatted.append(f"- Diagram types: {', '.join(summary.get('diagram_types', []))}")
            formatted.append(f"- Total classes: {summary.get('total_classes', 0)}")
            formatted.append(f"- Total actors: {summary.get('total_actors', 0)}")
            formatted.append(f"- Total relationships: {summary.get('total_relationships', 0)}")
       
        return '\n'.join(formatted)
   
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Claude's response into structured data with autonomous parsing."""
        try:
            # Use the enhanced autonomous parser
            from utils.response_parser_working import StreamingResponseParser
            parser = StreamingResponseParser()
            result = parser.parse_claude_response(response_text)
           
            logger.info(f"✅ Autonomous parsing successful: {len(result.get('files', {}))} files found")
            return result
           
        except Exception as e:
            logger.error(f"Autonomous parsing failed: {str(e)}")
            logger.info("🔄 Falling back to built-in parser...")
            # Fallback parsing
            return self._fallback_parse(response_text)
   
    def _fallback_parse(self, response_text: str) -> Dict[str, Any]:
        """Fallback parsing when autonomous parser fails."""
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                parsed_json = json.loads(json_str)
                logger.info("✅ Fallback parsing successful using regex extraction")
                return parsed_json
           
            # Try parsing entire response as JSON
            try:
                parsed_json = json.loads(response_text.strip())
                logger.info("✅ Fallback parsing successful using direct JSON parsing")
                return parsed_json
            except json.JSONDecodeError:
                logger.warning("⚠️ JSON parsing failed, creating structured response with raw content")
                # Create structured response with raw content
                return {
                    "project_structure": {
                        "solution_name": "GeneratedProject",
                        "projects": [
                            {
                                "name": "GeneratedProject.Core",
                                "type": "ClassLibrary",
                                "framework": "net8.0"
                            }
                        ]
                    },
                    "files": {
                        "raw_response.txt": {
                            "content": response_text,
                            "type": "text"
                        }
                    },
                    "dependencies": [],
                    "configuration": {},
                    "_parsing_note": "Fallback parsing applied - raw response preserved"
                }
       
        except Exception as e:
            logger.error(f"Fallback parsing failed: {str(e)}")
            raise ValueError(f"Failed to parse response: {str(e)}")

    def _diagnose_response_issues(self, response: str) -> list:
        """Diagnose common issues in AI responses"""
        issues = []
       
        try:
            # Check for JSON structure issues
            if '```json' in response:
                json_start = response.find('```json') + 7
                json_end = response.find('```', json_start)
               
                if json_end == -1:
                    issues.append("unclosed_json_block")
                else:
                    json_content = response[json_start:json_end]
                   
                    # Check JSON validity
                    try:
                        json.loads(json_content)
                    except json.JSONDecodeError as e:
                        if "Unterminated string" in str(e):
                            issues.append("unterminated_string")
                        elif "Expecting" in str(e):
                            issues.append("malformed_json")
                        else:
                            issues.append("json_syntax_error")
                   
                    # Check brace balance
                    open_braces = json_content.count('{')
                    close_braces = json_content.count('}')
                    if abs(open_braces - close_braces) > 2:
                        issues.append("unbalanced_braces")
           
            # Check for content completeness
            if len(response) < 5000:
                issues.append("response_too_short")
           
            if not any(end in response[-100:] for end in ['}', '```', '"']):
                issues.append("abrupt_ending")
           
        except Exception as e:
            logger.warning(f"Issue diagnosis failed: {str(e)}")
            issues.append("diagnosis_failed")
       
        return issues

    # Backward compatibility and utility methods
    def generate_code_streaming(self, request: GenerationRequest, temp_file_callback=None) -> GenerationResponse:
        """Backward compatibility - redirect to main generate_code method."""
        logger.info("🔄 Redirecting streaming request to autonomous generation method")
        return self.generate_code(request)
   
    def _create_temp_stream_file(self) -> str:
        """Backward compatibility method."""
        return self._create_autonomous_raw_file()
   
    def _process_streaming_response(self, response, temp_file_path: str, callback=None) -> str:
        """Backward compatibility method."""
        return self._process_autonomous_streaming(response, temp_file_path)
   
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model configuration."""
        return {
            "model_id": self.model_id,
            "aws_region": self.aws_region,
            "aws_profile": self.aws_profile,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "client_initialized": self.bedrock_client is not None
        }
   
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection to AWS Bedrock."""
        try:
            # Simple test request
            test_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "temperature": 0.1,
                "messages": [{"role": "user", "content": "Test connection. Reply with 'Connection successful'."}]
            }
           
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(test_body),
                contentType='application/json',
                accept='application/json'
            )
           
            response_body = json.loads(response['body'].read())
           
            return {
                "connection_status": "success",
                "model_id": self.model_id,
                "response_received": True,
                "test_response": response_body.get('content', [{}])[0].get('text', 'No text received')
            }
           
        except Exception as e:
            return {
                "connection_status": "failed",
                "error": str(e),
                "model_id": self.model_id,
                "recommendations": [
                    "Check AWS credentials",
                    "Verify AWS profile configuration",
                    "Ensure Bedrock service is available in the region",
                    "Check model access permissions"
                ]
            }
   
    def get_usage_statistics(self) -> Dict[str, Any]:
        """Get usage statistics (placeholder for future implementation)."""
        return {
            "total_requests": 0,  # Would track in production
            "successful_generations": 0,
            "failed_generations": 0,
            "average_response_time": 0,
            "total_tokens_used": 0,
            "note": "Statistics tracking not implemented in this version"
        }
   
    def cleanup_temp_files(self, older_than_hours: int = 24) -> Dict[str, Any]:
        """Clean up old temporary response files."""
        try:
            output_dir = Path("generated_output")
            if not output_dir.exists():
                return {"status": "no_cleanup_needed", "message": "Output directory doesn't exist"}
           
            import time
            current_time = time.time()
            cutoff_time = current_time - (older_than_hours * 3600)
           
            cleaned_files = []
            total_size_cleaned = 0
           
            for file_path in output_dir.glob("raw_response_*.txt"):
                if file_path.stat().st_mtime < cutoff_time:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    cleaned_files.append(str(file_path))
                    total_size_cleaned += file_size
           
            return {
                "status": "success",
                "files_cleaned": len(cleaned_files),
                "size_cleaned_mb": round(total_size_cleaned / (1024 * 1024), 2),
                "cutoff_hours": older_than_hours
            }
           
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
       
    def _detect_and_complete_truncated_response(self, response: str, attempt: int = 0) -> str:
        """Detect truncated responses and automatically request completion"""
        if attempt >= 5:  # Increased from 3 to 5
            logger.warning("Max completion attempts reached, returning current response")
            return response
       
        # More aggressive truncation detection
        truncation_issues = []
       
        # Check for unmatched braces
        open_braces = response.count('{')
        close_braces = response.count('}')
        if open_braces > close_braces + 1:  # Reduced tolerance
            truncation_issues.append(f"Missing {open_braces - close_braces} closing braces")
       
        # Check for incomplete FILE blocks
        file_markers = response.count('**FILE:')
        if file_markers > 0:
            # Check if last file block is complete
            last_file_pos = response.rfind('**FILE:')
            content_after_last_file = response[last_file_pos:]
            if not ('```' in content_after_last_file and content_after_last_file.count('```') >= 2):
                truncation_issues.append("Incomplete file block detected")
       
        # Check for abrupt code endings
        if response.rstrip().endswith(('public class', 'private', 'public', 'namespace', 'using', '{', 'private readonly')):
            truncation_issues.append("Code ends abruptly mid-declaration")
       
        # Check for incomplete method signatures
        try:
            last_lines = '\n'.join(response.split('\n')[-3:])  # Convert list back to string
            if re.search(r'(public|private)\s+\w+\s*$[^)]*\$', last_lines):
                truncation_issues.append("Incomplete method signature detected")
        except Exception as regex_error:
            logger.debug(f"Regex check failed: {str(regex_error)}")
       
        if not truncation_issues:
            logger.info("✅ Response appears complete")
            return response
       
        logger.warning(f"🔧 Truncation detected: {', '.join(truncation_issues)}")
        logger.info(f"🔄 Requesting completion (attempt {attempt + 1}/5)...")
       
        # More specific continuation prompt
        continuation_prompt = f"""CONTINUATION REQUIRED - The previous C# code generation was cut off.

    Here's what was generated so far (last 800 characters):
    {response[-800:]}

    ISSUES DETECTED: {', '.join(truncation_issues)}

    Please complete ONLY the missing parts:
    1. Finish any incomplete class definitions with proper closing braces
    2. Complete any cut-off method implementations  
    3. Add any missing file content that was truncated
    4. Ensure all **FILE:** blocks are properly completed

    IMPORTANT:
    - Only provide C# .NET 8 code (NO PHP)
    - Continue exactly where the previous response ended
    - Use the same **FILE:** format for any new files
    - Focus on completing the truncated content, not generating new features

    Complete the truncated response now:"""

        try:
            # Completion request with higher token limit
            completion_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,  # Increased from 2000
                "temperature": 0.01,  # Even more focused
                "messages": [{"role": "user", "content": continuation_prompt}]
            }
           
            # Get completion
            completion_response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(completion_body),
                contentType='application/json',
                accept='application/json'
            )
           
            completion_data = json.loads(completion_response['body'].read())
            completion_text = completion_data.get('content', [{}])[0].get('text', '')
           
            if completion_text.strip():
                logger.info(f"✅ Received completion: {len(completion_text)} chars")
                # Merge the completion with original response
                merged_response = response + "\n" + completion_text
               
                # Recursively check if we need more completion
                return self._detect_and_complete_truncated_response(merged_response, attempt + 1)
            else:
                logger.warning("⚠️ Empty completion received")
                return response
               
        except Exception as e:
            logger.error(f"❌ Completion request failed: {str(e)}")
            return response

# Utility functions for external use
def create_generation_request(
    parsed_data: Dict[str, Any],
    target_language: str = "csharp",
    framework: str = "net8.0",
    coding_standards: str = "Microsoft",
    architecture_pattern: str = "Clean Architecture",
    include_tests: bool = True,
    include_docs: bool = True,
    custom_instructions: str = None
) -> GenerationRequest:
    """Utility function to create a GenerationRequest."""
    return GenerationRequest(
        parsed_data=parsed_data,
        target_language=target_language,
        framework=framework,
        coding_standards=coding_standards,
        architecture_pattern=architecture_pattern,
        include_tests=include_tests,
        include_docs=include_docs,
        custom_instructions=custom_instructions
    )

def quick_generate(
    parsed_data: Dict[str, Any],
    aws_profile: str = "default",
    **kwargs
) -> GenerationResponse:
    """Quick utility function to generate code with default settings."""
    client = ClaudeClient(aws_profile=aws_profile)
   
    request = create_generation_request(parsed_data, **kwargs)
   
    return client.generate_code(request)

# Test and example usage
def test_claude_client():
    """Test the Claude client with sample data."""
    print("🧪 Testing Claude Client...")
   
    # Create test client
    try:
        client = ClaudeClient()
        print("✅ Client initialized successfully")
       
        # Test connection
        connection_test = client.test_connection()
        print(f"🔗 Connection test: {connection_test['connection_status']}")
       
        if connection_test['connection_status'] == 'failed':
            print(f"❌ Connection failed: {connection_test['error']}")
            return False
       
        # Test with minimal data
        test_data = {
            "story_info": {
                "story_key": "TEST-001",
                "summary": "Test application",
                "user_story": "As a developer, I want to test the Claude client, so that I can verify it works"
            },
            "acceptance_criteria": [
                "Application should compile successfully",
                "Application should run without errors"
            ],
            "business_value": {
                "description": "Validates the code generation pipeline",
                "benefits": ["Automated testing", "Quality assurance"],
                "priority": "High"
            },
            "class_diagram": {
                "classes": ["TestClass"],
                "raw_diagram": "Simple test diagram"
            },
            "sequence_diagram": {
                "participants": ["User", "System"],
                "interactions": []
            }
        }
       
        request = create_generation_request(
            test_data,
            target_language="csharp",
            framework="net8.0",
            include_tests=False,
            include_docs=False,
            custom_instructions="Generate minimal console application for testing"
        )
       
        print("🚀 Starting test generation...")
        response = client.generate_code(request)
       
        if response.success:
            print("✅ Test generation successful!")
            print(f"📊 Files generated: {len(response.generated_code.get('files', {}))}")
            return True
        else:
            print(f"❌ Test generation failed: {response.error_message}")
            return False
           
    except Exception as e:
        print(f"❌ Test failed with exception: {str(e)}")
        return False

if __name__ == "__main__":
    # Run test if this file is executed directly
    success = test_claude_client()
    print(f"\n🎯 Claude Client test {'PASSED' if success else 'FAILED'}")
